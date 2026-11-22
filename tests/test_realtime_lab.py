import asyncio
import base64
import json
from pathlib import Path
import tempfile
import unittest

from tavi.realtime_lab import NativeSession
from tavi.storage import Store, APPROVED_BUDGET_MICRO_USD


class Detector:
    def __init__(self):self.p=0
    def probability(self,pcm):return self.p


class Provider:
    def __init__(self):self.sent=[];self.events=asyncio.Queue();self.closed=False
    async def connect(self):pass
    async def receive(self):return await self.events.get()
    async def send(self,kind,**data):self.sent.append({'type':kind,**data})
    async def close(self):self.closed=True


class Tests(unittest.IsolatedAsyncioTestCase):
    async def make(self,audio=False):
        store=Store();detector=Detector();provider=Provider();session=NativeSession(store,'a'*32,detector=detector,provider=provider)
        await session.prepare({'adult':True,'cloud':True,'recording':True,'save_audio':audio},record_workflow=False)
        self.addAsyncCleanup(session.stop)
        return store,detector,provider,session

    async def feed(self,session,detector,p,n):
        detector.p=p
        for _ in range(n):await session.frame({'sequence':session.sequence+1,'pcm':base64.b64encode(b'\0'*1024).decode()})

    async def flush(self):
        for _ in range(4):await asyncio.sleep(0)

    async def test_explicit_scope_and_before_audio_budget(self):
        store=Store();provider=Provider();s=NativeSession(store,'a'*32,detector=Detector(),provider=provider)
        with self.assertRaises(ValueError):await s.prepare({'adult':False,'cloud':True,'recording':True,'save_audio':False},record_workflow=False)
        self.assertEqual(provider.sent,[])
        store,d,p,s=await self.make();store.reserve('full',APPROVED_BUDGET_MICRO_USD,APPROVED_BUDGET_MICRO_USD)
        await self.feed(s,d,.9,1)
        with self.assertRaises(ValueError):await self.feed(s,d,.9,1)
        self.assertEqual(p.sent,[],'reserve before sending audio')
        store2,d2,p2,s2=await self.make();s2.maximum_requests=1;s2.reserved_calls=1
        await self.feed(s2,d2,.9,1)
        with self.assertRaises(ValueError):await self.feed(s2,d2,.9,1)
        self.assertEqual(p2.sent,[],'fixture request ceiling before sending audio')

    async def test_turn_end_and_actual_played_truncation(self):
        store,d,p,s=await self.make(audio=True)
        await self.feed(s,d,.9,9);await self.feed(s,d,.01,18)
        self.assertEqual([e['type'] for e in p.sent][-2:],['input_audio_buffer.commit','response.create'])
        self.assertEqual(store.used_micro_usd(),1_000_000)
        self.assertEqual(len(s.pending['input_pcm24_sha256']),64)
        self.assertGreater(s.pending['input_pcm24_bytes'],0)
        for e in [{'type':'response.created','response':{'id':'r'}},
                  {'type':'response.output_item.added','item':{'id':'i'}},
                  {'type':'response.output_audio.delta','response_id':'r','item_id':'i','delta':base64.b64encode(b'\0'*48000).decode()}]:
            await p.events.put(e)
        await self.flush()
        await s.interrupt({'id':'r','played_ms':380})
        self.assertEqual(p.sent[-2]['type'],'response.cancel')
        self.assertEqual(p.sent[-1]['audio_end_ms'],380)
        for e in [{'type':'response.output_audio.delta','response_id':'r','item_id':'i','delta':base64.b64encode(b'\0'*4800).decode()},
                  {'type':'response.done','response':{'id':'r','status':'cancelled','usage':{'input_tokens':100,'output_tokens':20}}},
                  {'type':'conversation.item.truncated','item_id':'i','audio_end_ms':380}]:await p.events.put(e)
        await self.flush()
        self.assertTrue(s.current['truncated_ack']);self.assertEqual(store.used_micro_usd(),4480)
        self.assertFalse(any(e['kind']=='audio' for e in s.out),'late cancelled audio suppressed')
        await s.stop()
        with tempfile.TemporaryDirectory() as root:
            result=await s.save({'ratings':{},'note':'partial'},data_root=root)
            record=json.loads((Path(root)/result['file']).read_text())
            self.assertTrue(record['include_audio']);self.assertIn('pcm16_16000_base64',record)
            self.assertTrue(all(v is None for v in record['ratings'].values()))
            self.assertEqual(await s.save({},data_root=root),result)
            self.assertEqual((Path(root)/result['file']).stat().st_mode&0o777,0o600)

    async def test_no_audio_save_after_normal_close_and_gaps_fail_closed(self):
        store,d,p,s=await self.make()
        await self.feed(s,d,.01,2)
        with self.assertRaises(ValueError):await s.frame({'sequence':5,'pcm':base64.b64encode(b'\0'*1024).decode()})
        with self.assertRaises(ValueError):await s.save({})
        await s.stop();self.assertTrue(p.closed)
        with tempfile.TemporaryDirectory() as root:
            result=await s.save({'ratings':{'quiet_complete':'unsure'},'note':'partial'},data_root=root)
            record=json.loads((Path(root)/result['file']).read_text())
            self.assertNotIn('pcm16_16000_base64',record)
            self.assertFalse(record['include_audio'])
        self.assertEqual(len(s.recording),0)
        with self.assertRaises(ValueError):await self.feed(s,d,.9,1)

    async def test_overlap_without_local_stop_cannot_create_next_response(self):
        store,d,p,s=await self.make()
        s.current={'response_id':'old','item_id':'olditem','done':True,'played':False,'blocked':False,'frames':24000}
        s.rows.append(s.current)
        await self.feed(s,d,.9,9)
        with self.assertRaises(ValueError):await self.feed(s,d,0,18)
        self.assertNotIn('response.create',[e['type'] for e in p.sent])
        with self.assertRaises(ValueError):await s.interrupt({'id':'old','played_ms':1001})
        await s.interrupt({'id':'old','played_ms':500})
        self.assertNotIn('response.cancel',[e['type'] for e in p.sent])
        self.assertEqual(p.sent[-1]['type'],'conversation.item.truncate')

    async def test_unbound_provider_audio_stops_further_frames(self):
        store,d,p,s=await self.make()
        await p.events.put({'type':'response.output_audio.delta','response_id':'bad','item_id':'bad','delta':''})
        await self.flush();self.assertIsNotNone(s.error)
        with self.assertRaises(ValueError):await self.feed(s,d,.9,1)

    async def test_save_collision_preserves_original_temp_and_unarmed_watchdog(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from tavi.realtime_lab import NativeLab
        import time
        store,d,p,s=await self.make()
        await s.stop()
        with tempfile.TemporaryDirectory() as root:
            original=Path(root)/('.'+s.id+'.fixed.tmp');original.write_text('preserve me')
            with patch('tavi.realtime_lab.uuid4',return_value=SimpleNamespace(hex='fixed')):
                with self.assertRaises(FileExistsError):await s.save({'ratings':{}},data_root=root)
            self.assertEqual(original.read_text(),'preserve me')
        store2,d2,p2,s2=await self.make()
        s2.started=s2.last_frame=time.monotonic()-61
        lab=NativeLab(store2);lab.sessions[s2.id]=s2
        task=asyncio.create_task(lab.watchdog())
        try:
            await asyncio.sleep(.3)
            self.assertTrue(s2.stopped);self.assertTrue(p2.closed)
        finally:
            task.cancel();await asyncio.gather(task,return_exceptions=True)

    async def test_http_origin_private_route_and_bounded_actions(self):
        import threading
        from http.server import ThreadingHTTPServer
        from urllib.request import Request,urlopen
        from urllib.error import HTTPError
        from tavi.realtime_service import handler
        class Lab:
            def __init__(self):self.calls=[]
            async def action(self,path,body):self.calls.append(path);return {'saved':True}
        lab=Lab();server=ThreadingHTTPServer(('127.0.0.1',0),lambda *a:None)
        port=server.server_port;server.RequestHandlerClass=handler(lab,asyncio.get_running_loop(),port)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        origin=f'http://127.0.0.1:{port}'
        def request(path,body=None,source=None):
            req=Request(origin+path,data=body,headers={'Origin':source or origin,'Content-Type':'application/json'})
            try:
                with urlopen(req,timeout=2) as response:return response.status,response.read()
            except HTTPError as exc:return exc.code,exc.read()
        try:
            self.assertEqual((await asyncio.to_thread(request,'/'))[0],200)
            self.assertEqual((await asyncio.to_thread(request,'/.tavi/private-native-references/file.json'))[0],404)
            self.assertEqual((await asyncio.to_thread(request,'/prepare',b'{}','https://foreign.example'))[0],403)
            self.assertEqual(lab.calls,[])
            self.assertEqual((await asyncio.to_thread(request,'/frame',b' '*80001))[0],400)
            self.assertEqual((await asyncio.to_thread(request,'/save',b'{}'))[0],200)
            self.assertEqual(lab.calls,['/save'])
        finally:
            await asyncio.to_thread(server.shutdown);server.server_close()

    async def test_closure_has_two_request_bound_and_preserves_missing_labels(self):
        store=Store();provider=Provider();detector=Detector();s=NativeSession(store,'b'*32,provider=provider,detector=detector)
        await s.prepare({'adult':True,'cloud':True,'recording':True,'save_audio':False,'workflow':'closure-v2'},record_workflow=False)
        self.assertEqual(s.maximum_requests,2)
        await s.stop()
        with tempfile.TemporaryDirectory() as root:
            result=await s.save({'ratings':{'goodbye':'no','no_reintroduction':'yes'}},data_root=root)
            saved=json.loads((Path(root)/result['file']).read_text())
            self.assertEqual(saved['choices']['workflow'],'closure-v2')
            self.assertEqual(set(saved['ratings']),{'quiet_complete','goodbye','no_reintroduction','responsive'})
            self.assertIsNone(saved['ratings']['quiet_complete'])
            self.assertNotIn('pcm16_16000_base64',saved)
