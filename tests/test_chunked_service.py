import asyncio
from http.client import HTTPConnection
import json
import threading
import unittest
from unittest.mock import patch

from tavi.service import Demo, LocalHTTPServer, handler_for
from tavi.storage import Store
from tavi.conversation_providers import Speech


class ChunkServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_chunk_identity_headers_and_browser_configuration(self):
        class Voice:
            async def synthesize(self,text): return Speech(b'synthetic-wave',1000)
        class Live:
            def start(self,mode): return {'stream_id':'fixture','sample_rate':16000}
            def feed(self,*args):
                return {'events':[{'type':'speech_started','utterance':1},
                     {'type':'recognition','utterance':1,'text':'Paprika','final':True,'first_detection':True}],
                        'probability':0,'sequence':0}
            def stop(self,*args): return {'stopped':True}
            def expire(self): pass
            def close(self): pass
        store=Store(); demo=Demo(store); loop=asyncio.get_running_loop()
        server=LocalHTTPServer(('127.0.0.1',0),lambda *a:None); port=server.server_port
        with patch('tavi.conversation.MacSpeech',Voice):
            server.RequestHandlerClass=handler_for(demo,loop,port,live_factory=Live,reply_delivery='sentences')
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def request(path,body=None,headers=None):
            conn=HTTPConnection('127.0.0.1',port,timeout=3)
            try:
                raw=json.dumps(body) if isinstance(body,dict) else body
                h={'Origin':f'http://127.0.0.1:{port}','X-Audio-Stream':'fixture',**(headers or {})}
                if isinstance(body,dict): h['Content-Type']='application/json'
                conn.request('GET' if body is None else 'POST',path,body=raw,headers=h)
                response=conn.getresponse();return response.status,response.read()
            finally: conn.close()
        try:
            status,page=await asyncio.to_thread(request,'/conversation?workflow=latency')
            self.assertEqual(status,200);self.assertIn(b'data-delivery="sentences"',page)
            status,body=await asyncio.to_thread(request,'/api/conversation/start',{'online':False})
            self.assertEqual(status,200);self.assertEqual(json.loads(body)['conversation']['reply_delivery'],'sentences')
            await asyncio.to_thread(request,'/api/conversation/frame',bytes(1024),
                                    {'Content-Type':'application/octet-stream','X-Audio-Sequence':'0'})
            for _ in range(50):
                _,raw=await asyncio.to_thread(request,'/api/conversation/diagnostics')
                state=json.loads(raw)
                if state['audio']:break
                await asyncio.sleep(.01)
            rid=state['audio']['id']
            self.assertEqual((await asyncio.to_thread(request,'/api/conversation/audio',None,{'X-Response-Id':rid}))[0],400)
            self.assertEqual((await asyncio.to_thread(request,'/api/conversation/audio',None,{'X-Response-Id':rid,'X-Audio-Sequence':'1'}))[0],400)
            status,wav=await asyncio.to_thread(request,'/api/conversation/audio',None,{'X-Response-Id':rid,'X-Audio-Sequence':'0'})
            self.assertEqual(status,200);self.assertEqual(wav,b'synthetic-wave')
            for command in ('started','played'):
                status,body=await asyncio.to_thread(request,'/api/conversation/'+command,{'response_id':rid,'sequence':0})
                self.assertEqual(status,200);self.assertTrue(json.loads(body)['accepted'])
            self.assertEqual(json.loads(body)['conversation']['completed_response_id'],rid)
            self.assertEqual(store.used_micro_usd(),0)
        finally:
            await server.RequestHandlerClass.close_conversation()
            await asyncio.to_thread(server.shutdown);server.server_close();await demo.close();store.close()


if __name__=='__main__':unittest.main()
