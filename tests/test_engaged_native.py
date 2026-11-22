import asyncio
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest

from tavi.asr_confidence import DecodedSpeech
from tavi.engaged_native import EngagedNativeSession, SharedPlayContext
from tavi.storage import Store


class Detector:
    p=0
    def probability(self, pcm):return self.p


class Decoder:
    def __init__(self):self.text='';self.inputs=[];self.cancelled=False;self.profile={'test_double':True}
    def prepare(self):pass
    def decode(self, pcm, deadline, valid):
        if not valid():raise ValueError('Expired')
        self.inputs.append(pcm)
        return DecodedSpeech(self.text,{})
    def cancel(self):self.cancelled=True
    def close(self):pass


class Provider:
    def __init__(self):self.sent=[];self.events=asyncio.Queue();self.connections=0;self.closed=False
    async def connect(self):self.connections+=1;self.closed=False
    async def receive(self):return await self.events.get()
    async def send(self, kind, **fields):self.sent.append({'type':kind,**fields})
    async def close(self):self.closed=True


class Tests(unittest.IsolatedAsyncioTestCase):
    async def make(self):
        store=Store();detector=Detector();decoder=Decoder();provider=Provider()
        s=EngagedNativeSession(store,'c'*32,detector=detector,decoder=decoder,provider=provider)
        await s.prepare({'adult':True,'cloud':True,'recording':True,'save_audio':False,
                         'context_fixture':True,'workflow':'engagement-v1'},record_workflow=False)
        self.addAsyncCleanup(s.stop)
        return s,detector,decoder,provider,store

    async def feed(self,s,d,p,n):
        d.p=p
        results=[]
        if not hasattr(s,'test_pcm'):s.test_pcm=bytearray()
        for _ in range(n):
            pcm=((s.sequence+2)%30000).to_bytes(2,'little')*512
            s.test_pcm.extend(pcm)
            results.append(await s.frame({'sequence':s.sequence+1,'pcm':base64.b64encode(pcm).decode()}))
        return results

    async def wake(self,s,d,decoder,text='Paprika, what is our pretend fort called?'):
        decoder.text=text
        await self.feed(s,d,.9,9);await self.feed(s,d,0,25)
        if s.local_job:await s.local_job

    async def response(self,s,p,index=1):
        for event in [
            {'type':'response.created','response':{'id':f'r{index}'}},
            {'type':'response.output_item.added','item':{'id':f'i{index}'}},
            {'type':'response.output_audio.delta','response_id':f'r{index}','item_id':f'i{index}',
             'delta':base64.b64encode(bytes(48000)).decode()},
            {'type':'response.done','response':{'id':f'r{index}','status':'completed',
                                              'usage':{'input_tokens':100,'output_tokens':20}}}]:await p.events.put(event)
        for _ in range(8):await asyncio.sleep(0)

    async def test_standby_never_connects_sends_or_reserves(self):
        s,d,decoder,p,store=await self.make()
        await self.wake(s,d,decoder,'I wonder what we could build next.')
        self.assertEqual(s.mode,'standby');self.assertEqual(p.connections,0)
        self.assertEqual(p.sent,[]);self.assertEqual(store.used_micro_usd(),0)
        self.assertTrue(any(e['kind']=='standby_rejected' for e in s.out))
        await self.wake(s,d,decoder,'We could put paprika in the soup.')
        self.assertEqual(p.sent,[],'a name mentioned mid-utterance must stay local')

    async def test_first_complete_audio_and_context_bound_before_response(self):
        s,d,decoder,p,store=await self.make()
        await self.wake(s,d,decoder)
        self.assertEqual(s.mode,'active');self.assertEqual(p.connections,1)
        self.assertEqual(store.used_micro_usd(),1_000_000)
        self.assertEqual([x['type'] for x in p.sent],['input_audio_buffer.append','input_audio_buffer.commit','response.create'])
        self.assertEqual(len(decoder.inputs),1)
        import audioop
        actual=base64.b64decode(p.sent[0]['audio'])
        self.assertEqual(actual,audioop.ratecv(decoder.inputs[0],2,1,16000,24000,None)[0])
        pending=s.pending
        self.assertEqual(pending['input_pcm24_sha256'],hashlib.sha256(actual).hexdigest())
        self.assertEqual(pending['speaker'],'unknown')
        self.assertEqual(pending['context_fact_ids'],['pretend-fort','pretend-mascot'])
        self.assertIn('Star Nest',p.sent[-1]['response']['instructions'])
        self.assertIn('Pixel',p.sent[-1]['response']['instructions'])
        self.assertNotIn('Adult One',p.sent[-1]['response']['instructions'])

    async def test_followup_no_name_and_goodbye_closes_only_after_playback(self):
        s,d,decoder,p,store=await self.make();await self.wake(s,d,decoder)
        await self.response(s,p);await s.played({'id':'r1'})
        decoder.text='Goodbye, Paprika.'
        await self.feed(s,d,.9,9);await self.feed(s,d,0,18)
        import audioop
        pending=s.pending
        selected=bytes(s.test_pcm[pending['input_start_sample']*2:pending['input_end_sample']*2])
        converted,_=audioop.ratecv(selected,2,1,16000,24000,None)
        self.assertEqual(hashlib.sha256(converted).hexdigest(),pending['input_pcm24_sha256'])
        await s.closure_job
        self.assertEqual(p.connections,1,'follow-up reuses the engaged channel')
        self.assertEqual(sum(x['type']=='response.create' for x in p.sent),2)
        await self.response(s,p,2)
        await self.feed(s,d,0,1)
        self.assertEqual(s.mode,'active','generation done is not playback done')
        await s.played({'id':'r2'});await self.feed(s,d,0,1)
        await s.closing_job
        self.assertEqual(s.mode,'standby');self.assertTrue(p.closed)
        sent=len(p.sent);spent=store.used_micro_usd()
        await self.wake(s,d,decoder,'What should we build?')
        self.assertEqual(len(p.sent),sent);self.assertEqual(store.used_micro_usd(),spent)
        await self.wake(s,d,decoder)
        self.assertEqual(p.connections,2,'a new wake opens a fresh history/channel')

    async def test_idle_requires_settled_playback_and_has_no_remote_speech(self):
        s,d,decoder,p,store=await self.make();await self.wake(s,d,decoder)
        await self.response(s,p);s.idle_since=time.monotonic()-21
        await self.feed(s,d,0,1);self.assertEqual(s.mode,'active')
        await s.played({'id':'r1'});s.idle_since=time.monotonic()-21
        await self.feed(s,d,0,1);await s.closing_job;self.assertEqual(s.mode,'standby')
        self.assertTrue(any(e['kind']=='returned_to_local_standby' and e['reason']=='idle' for e in s.trace))

    async def test_unconfirmed_overlap_cannot_replace_context_or_create_response(self):
        s,d,decoder,p,store=await self.make();await self.wake(s,d,decoder);await self.response(s,p)
        decoder.text='Wait, make it a space adventure instead.'
        await self.feed(s,d,.9,9)
        with self.assertRaises(ValueError):await self.feed(s,d,0,18)
        self.assertEqual(sum(x['type']=='response.create' for x in p.sent),1)

    async def test_stopped_local_decode_cannot_activate_or_charge(self):
        s,d,decoder,p,store=await self.make()
        waiting=asyncio.Event()
        async def delayed(pcm,epoch):await waiting.wait();return 'Paprika, hello.'
        s.decode_local=delayed
        await self.feed(s,d,.9,9);await self.feed(s,d,0,25)
        await s.stop();waiting.set();await asyncio.sleep(0)
        self.assertEqual(p.sent,[]);self.assertEqual(p.connections,0);self.assertEqual(store.used_micro_usd(),0)

    async def test_slow_cloud_close_cannot_block_the_microphone_frame_path(self):
        s,d,decoder,p,store=await self.make();await self.wake(s,d,decoder)
        await self.response(s,p);await s.played({'id':'r1'})
        s.close_reservation=s.current['reservation_id']
        release=asyncio.Event()
        async def slow_close():await release.wait();p.closed=True
        p.close=slow_close
        try:
            await asyncio.wait_for(self.feed(s,d,0,1),.2)
            self.assertEqual(s.mode,'closing')
            await asyncio.wait_for(self.feed(s,d,0,3),.2)
            self.assertEqual(sum(e['type']=='response.create' for e in p.sent),1)
        finally:release.set()
        for _ in range(8):await asyncio.sleep(0)
        self.assertEqual(s.mode,'standby')

    async def test_twenty_second_first_input_is_not_rejected_by_followup_buffer_limit(self):
        s,d,decoder,p,store=await self.make()
        decoder.text='Paprika, here is a longer request.'
        await s.activate(bytes(640000),0,320000,s.epoch)
        self.assertIsNone(s.error);self.assertEqual(s.mode,'active')
        self.assertEqual(s.pending['input_end_sample'],320000)

    async def test_settled_interruption_still_has_a_bounded_idle_exit(self):
        s,d,decoder,p,store=await self.make();await self.wake(s,d,decoder)
        await self.response(s,p)
        await s.interrupt({'id':'r1','played_ms':0})
        await p.events.put({'type':'conversation.item.truncated','item_id':'i1','audio_end_ms':0})
        for _ in range(8):await asyncio.sleep(0)
        await self.feed(s,d,0,1);self.assertIsNotNone(s.idle_since)
        s.idle_since=time.monotonic()-21
        await self.feed(s,d,0,1);await s.closing_job
        self.assertEqual(s.mode,'standby');self.assertTrue(p.closed)

    async def test_context_refuses_personal_and_oversized_data(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'context.json'
            path.write_text(json.dumps({'kind':'fictional_shared_play','facts':[
                {'id':'private','audience':'person','text':'private fact'}]}))
            with self.assertRaises(ValueError):SharedPlayContext(path)
            path.write_text(' '*4001)
            with self.assertRaises(ValueError):SharedPlayContext(path)
