import base64
import json
import unittest
from unittest.mock import patch

from tavi.realtime_reference import (RealtimeReference, OutputGate, session_config,
                                     charge_usage, RESERVATION)
from tavi.storage import Store, APPROVED_BUDGET_MICRO_USD


class Socket:
    def __init__(self, events): self.events=list(events);self.sent=[];self.closed=False
    async def send(self, data): self.sent.append(json.loads(data))
    async def recv(self): return json.dumps(self.events.pop(0))
    async def close(self): self.closed=True


def events(interrupt=False, usage=True):
    data = [
        {'type':'response.created','response':{'id':'r1'}},
        {'type':'response.output_item.added','item':{'id':'i1'}},
        {'type':'response.output_audio.delta','response_id':'r1','item_id':'i1','content_index':0,
         'delta':base64.b64encode(b'\x00\x00'*2400).decode()},
        {'type':'response.output_audio.delta','response_id':'r1','item_id':'i1','content_index':0,
         'delta':base64.b64encode(b'\x00\x00'*2400).decode()},
        {'type':'response.done','response':{'id':'r1','status':'cancelled' if interrupt else 'completed',
          'usage':{'input_tokens':100,'output_tokens':20} if usage else None}}]
    if interrupt:data.append({'type':'conversation.item.truncated','item_id':'i1','audio_end_ms':0})
    return data


class Tests(unittest.IsolatedAsyncioTestCase):
    def test_gate_and_conservative_usage(self):
        gate=OutputGate();self.assertTrue(gate.accept(b'\x01\x00'*24))
        self.assertEqual(gate.stop()['heard_frames'],0)
        self.assertFalse(gate.accept(b'\x01\x00'*48))
        self.assertEqual(gate.dropped_frames,48)
        self.assertEqual(charge_usage({'input_tokens':100,'output_tokens':20}),4480)
        self.assertIsNone(charge_usage({'input_tokens':True,'output_tokens':20}))
        self.assertIsNone(charge_usage(None))

    async def test_no_saved_human_path_or_overbudget_transmission(self):
        store=Store();p=RealtimeReference(store);p.ws=Socket([])
        with self.assertRaises(ValueError):await p.turn(b'\x00'*4800,source_kind='new_adult_test')
        self.assertEqual(p.ws.sent,[]);self.assertEqual(store.used_micro_usd(),0)
        store.reserve('exhaust',APPROVED_BUDGET_MICRO_USD,APPROVED_BUDGET_MICRO_USD)
        with self.assertRaises(ValueError):await p.turn(b'\x00'*4800,source_kind='synthetic')
        self.assertEqual(p.ws.sent,[])

    async def test_verified_session_and_full_reply(self):
        sock=Socket([{'type':'session.created'},{'type':'session.updated','session':session_config()}]+events())
        async def connect():return sock
        store=Store();p=RealtimeReference(store,connector=connect)
        await p.connect()
        with patch('tavi.realtime_reference.asyncio.sleep',new=self.no_sleep):
            result=await p.turn(b'\x00'*4800,source_kind='synthetic')
        self.assertEqual(result['terminal_status'],'completed')
        self.assertEqual(store.used_micro_usd(),4480)
        self.assertEqual(sum(x['type']=='response.create' for x in sock.sent),1)
        self.assertFalse(result['physical_playback'])
        await p.close();self.assertTrue(sock.closed)

    async def test_interrupt_stops_before_network_and_late_audio_dropped(self):
        store=Store();p=RealtimeReference(store);sock=Socket(events(True));p.ws=sock
        sent=sock.send;observed=[]
        realstop=OutputGate.stop
        def stop(gate):observed.append('local');return realstop(gate)
        async def send(data):
            if json.loads(data)['type']=='response.cancel':observed.append('network')
            await sent(data)
        sock.send=send
        with patch.object(OutputGate,'stop',stop),patch('tavi.realtime_reference.asyncio.sleep',new=self.no_sleep):
            result=await p.turn(b'\x00'*4800,source_kind='synthetic',interrupt=True)
        self.assertEqual(observed,['local','network'])
        self.assertEqual(result['output_frames_dropped_after_stop'],2400)
        self.assertTrue(result['truncated_ack'])
        self.assertEqual(next(e for e in sock.sent if e['type']=='conversation.item.truncate')['audio_end_ms'],0)

    async def test_ambiguous_failure_retains_reservation_no_retry(self):
        store=Store();p=RealtimeReference(store);p.ws=Socket([{'type':'error','error':{'code':'bad_event'}}])
        with patch('tavi.realtime_reference.asyncio.sleep',new=self.no_sleep):
            with self.assertRaises(ValueError):await p.turn(b'\x00'*4800,source_kind='synthetic')
        self.assertEqual(store.used_micro_usd(),RESERVATION)
        self.assertEqual(sum(e['type']=='response.create' for e in p.ws.sent),1)
        store2=Store();p2=RealtimeReference(store2);p2.ws=Socket(events(usage=False))
        with patch('tavi.realtime_reference.asyncio.sleep',new=self.no_sleep):
            result=await p2.turn(b'\x00'*4800,source_kind='synthetic')
        self.assertFalse(result['usage_settled']);self.assertEqual(store2.used_micro_usd(),RESERVATION)

    @staticmethod
    async def no_sleep(_):pass
