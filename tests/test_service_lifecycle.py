import asyncio
from http.client import HTTPConnection
import json
import threading
import unittest
from unittest.mock import patch
from tavi.service import Demo, LocalHTTPServer, handler_for
from tavi.storage import Store


class ServiceLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def scenario(self, boundary, cancel=False):
        entered=threading.Event();release=threading.Event();calls=[]
        class Voice:
            async def prepare(self):
                if boundary=='voice':
                    entered.set();await asyncio.to_thread(release.wait,3)
            async def close(self):pass
        class Live:
            def start(self,mode):
                calls.append('start')
                if boundary=='live':entered.set();release.wait(3)
                return {'stream_id':'owned-fixture','sample_rate':16000}
            def stop(self,lease):calls.append(('stop',lease));return {'stopped':True}
            def close(self):pass
            def expire(self):pass
        store=Store();demo=Demo(store);server=LocalHTTPServer(('127.0.0.1',0),lambda *a:None);port=server.server_port
        with patch('tavi.local_speech.LocalSpeech',return_value=Voice()):
            handler=handler_for(demo,asyncio.get_running_loop(),port,live_factory=Live,voice_backend='kokoro-k',reply_delivery='sentences')
        server.RequestHandlerClass=handler;server.handle_error=lambda *args:None;thread=threading.Thread(target=server.serve_forever);thread.start()
        def request(route,body=None):
            conn=HTTPConnection('127.0.0.1',port,timeout=5)
            try:
                conn.request('GET' if body is None else 'POST',route,body=None if body is None else json.dumps(body),headers={'Content-Type':'application/json'})
                r=conn.getresponse();return r.status,json.loads(r.read())
            finally:conn.close()
        starting=asyncio.create_task(asyncio.to_thread(request,'/api/conversation/start',{'online':False}))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait,2))
            if cancel:
                task=next(t for t in asyncio.all_tasks() if t.get_coro().__qualname__.endswith('conversation_command'))
                task.cancel();await asyncio.sleep(0);release.set()
                from http.client import RemoteDisconnected
                with self.assertRaises(RemoteDisconnected):await starting
                # Closing waits for the cancelled thread's owned late lease cleanup.
                await handler.close_conversation()
            else:
                await handler.stop_capture();release.set()
                status,result=await starting;self.assertEqual(status,400);self.assertIn('cancelled',result['error'])
            _,diag=await asyncio.to_thread(request,'/api/conversation/diagnostics');self.assertFalse(diag['lease_active'])
            self.assertEqual(calls,[] if boundary=='voice' else ['start',('stop','owned-fixture')]);self.assertEqual(store.used_micro_usd(),0)
            if not cancel:
                status,_=await asyncio.to_thread(request,'/api/conversation/start',{'online':False});self.assertEqual(status,200)
                await handler.stop_capture()
        finally:
            release.set();await asyncio.gather(starting,return_exceptions=True);await handler.close_conversation();await asyncio.to_thread(handler.close_live)
            await asyncio.to_thread(server.shutdown);server.server_close();thread.join();await demo.close();store.close()
    async def test_pause_during_voice_preparation_never_starts_capture(self):await self.scenario('voice')
    async def test_pause_during_live_start_stops_only_that_late_lease(self):await self.scenario('live')
    async def test_timeout_cancellation_retires_late_owned_native_lease(self):await self.scenario('live',cancel=True)
