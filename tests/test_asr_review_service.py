import asyncio
import base64
from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace as NS
import unittest
from uuid import uuid4

from tavi.asr_review_service import ReviewLab,handler
from tavi.service import LocalHTTPServer
from tavi.storage import Store


class Decoder:
    profile={'model':'fake local'}
    def prepare(self):pass
    def decode(self,pcm,deadline,valid):
        if not valid():raise ValueError('Stopped')
        return NS(text='A bridge for two cars.',confidence={},timing={})
    def cancel(self):pass
    def close(self):pass


class ReviewLabTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store=Store();self.addCleanup(self.store.close)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.cloud_calls=[]
        parent=self
        class Cloud:
            async def transcribe(self,data,**kw):
                parent.cloud_calls.append(kw);return {'text':'A bridge for two cars.','elapsed_ms':10}
            async def close(self):pass
        self.lab=ReviewLab(self.store,Decoder(),Cloud,self.temp.name,record_workflow=False)
        self.addAsyncCleanup(self.lab.close)

    async def prepare(self,cloud=True):
        r=await self.lab.prepare({'session_id':uuid4().hex,'adult':True,'recording_consent':True,'cloud':cloud})
        return r['session_id']

    def clip(self,key,index=0):return {'session_id':key,'index':index,'pcm':base64.b64encode(bytes(256000)).decode()}

    async def test_explicit_adult_recording_and_destination_required(self):
        for body in ({},{'adult':True},{'adult':True,'recording_consent':True,'cloud':'yes'}):
            with self.assertRaises(ValueError):await self.lab.prepare(body)
        self.assertEqual(self.cloud_calls,[])

    async def test_cached_result_recovery_cannot_duplicate_paid_request(self):
        key=await self.prepare();body=self.clip(key)
        a=await self.lab.compare(body);b=await self.lab.compare(body)
        self.assertEqual(a,b);self.assertEqual(len(self.cloud_calls),1)
        self.assertEqual(self.cloud_calls[0],{'source_kind':'new_adult_test','consent':True})
        body['pcm']=base64.b64encode(bytes([1])*256000).decode()
        with self.assertRaisesRegex(ValueError,'cannot be replaced'):await self.lab.compare(body)

    async def test_local_only_never_calls_cloud_and_partial_save_excludes_audio(self):
        key=await self.prepare(cloud=False);body=self.clip(key);await self.lab.compare(body)
        with self.assertRaisesRegex(ValueError,'Stop capture'):await self.lab.save({**body,'clips':[]})
        await self.lab.stop(body)
        clip={'index':0,'pcm':body['pcm'],'settings':{'deviceId':'private-device','echoCancellation':True}}
        payload={'session_id':key,'include_audio':False,'reviews':[{'A':None}],'clips':[clip]}
        saved=await self.lab.save(payload);again=await self.lab.save(payload)
        self.assertEqual(saved['id'],again['id']);self.assertEqual(self.cloud_calls,[])
        path=Path(self.temp.name)/(saved['id']+'.json');r=json.loads(path.read_text())
        self.assertNotIn('pcm_base64',r['clips'][0]);self.assertNotIn('deviceId',r['clips'][0]['settings'])
        self.assertIsNone(r['reviews'][0]['A']);self.assertFalse(r['cloud_new_clips_consent'])
        self.assertEqual(path.stat().st_mode&0o777,0o600)

    async def test_saved_audio_must_match_compared_input_and_stop_prevents_new_call(self):
        key=await self.prepare();body=self.clip(key);await self.lab.compare(body);await self.lab.stop(body)
        with self.assertRaisesRegex(ValueError,'stopped'):await self.lab.compare(self.clip(key,1))
        letters=self.lab.sessions[key]['mapping'];reviews=[{k:'unsure' for k in letters}]
        bad={'index':0,'pcm':base64.b64encode(bytes([1])*256000).decode()}
        with self.assertRaisesRegex(ValueError,'differs'):await self.lab.save({'session_id':key,'include_audio':True,'reviews':reviews,'clips':[bad]})
        self.assertEqual(len(self.cloud_calls),1)

    async def test_stop_cancels_pending_cloud_without_recording_a_completed_turn(self):
        entered=asyncio.Event();cancelled=[]
        class HeldCloud:
            async def transcribe(self,*a,**kw):
                entered.set()
                try:await asyncio.Event().wait()
                finally:cancelled.append(True)
            async def close(self):pass
        self.lab.cloud_factory=HeldCloud;key=await self.prepare()
        task=asyncio.create_task(self.lab.compare(self.clip(key)));await entered.wait()
        await self.lab.stop({'session_id':key})
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(cancelled,[True]);self.assertEqual(self.lab.sessions[key]['results'],{})

    async def test_http_rejects_cross_origin_and_does_not_serve_private_files(self):
        server=LocalHTTPServer(('127.0.0.1',0),lambda *a:None);port=server.server_port
        server.RequestHandlerClass=handler(self.lab,asyncio.get_running_loop(),port)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def request(path,body=None,origin=None):
            conn=HTTPConnection('127.0.0.1',port,timeout=3)
            try:
                headers={'Content-Type':'application/json'}
                if origin:headers['Origin']=origin
                conn.request('POST' if body is not None else 'GET',path,json.dumps(body) if body is not None else None,headers)
                response=conn.getresponse();return response.status,response.read()
            finally:conn.close()
        try:
            self.assertEqual((await asyncio.to_thread(request,'/'))[0],200)
            self.assertEqual((await asyncio.to_thread(request,'/.tavi/private-asr-comparisons/x.json'))[0],404)
            self.assertEqual((await asyncio.to_thread(request,'/prepare',{},'https://outside.invalid'))[0],403)
        finally:await asyncio.to_thread(server.shutdown);server.server_close();thread.join(1)
