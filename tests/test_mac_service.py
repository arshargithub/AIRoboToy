import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
from tavi.mac_service import handler, CONSENT


class MacServiceTests(unittest.TestCase):
    def setUp(self):
        self.loop=asyncio.new_event_loop();self.thread=threading.Thread(target=self.loop.run_forever);self.thread.start()
        self.calls=[];calls=self.calls
        class Base(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def valid_host(self):return self.headers.get('Host')==f'127.0.0.1:{self.server.server_port}'
            def reply(self,status,data,mime='application/json'):
                raw=data if isinstance(data,bytes) else json.dumps(data).encode();self.send_response(status);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            def do_GET(self):calls.append(self.path);self.reply(200,{'diagnostics':True})
            def do_POST(self):calls.append((self.path,json.loads(self.rfile.read(int(self.headers['Content-Length'])))));self.reply(200,{'started':True})
            @staticmethod
            async def stop_capture():calls.append('pause')
        self.store=type('Store',(),{'used_micro_usd':lambda _:20496570})()
        self.server=ThreadingHTTPServer(('127.0.0.1',0),lambda *_:None);self.base=f'http://127.0.0.1:{self.server.server_port}'
        self.ready={'ready':True,'drive':True,'local_files':True,'cloud_key':True}
        self.server.RequestHandlerClass=handler(Base,self.loop,self.store,self.server.server_port,'a'*64,'b'*32,readiness=lambda:self.ready)
        self.http=threading.Thread(target=self.server.serve_forever);self.http.start()
        self.addCleanup(self.cleanup)
    def cleanup(self):
        self.server.shutdown();self.server.server_close();self.http.join();self.loop.call_soon_threadsafe(self.loop.stop);self.thread.join();self.loop.close()
    def request(self,path,body=None,auth=True,origin=None,host=None):
        headers={}
        if auth:headers['Authorization']='Bearer '+'a'*64
        if origin:headers['Origin']=origin
        if host:headers['Host']=host
        data=None if body is None else json.dumps(body).encode()
        if data:headers['Content-Type']='application/json'
        request=urllib.request.Request(self.base+path,data=data,headers=headers)
        try:
            with urllib.request.urlopen(request,timeout=3) as r:return r.status,r.read()
        except urllib.error.HTTPError as r:return r.code,r.read()
    def consent(self):return {'online':True,'consent':CONSENT,'adult':True,'local_audio_only':True,'retain_audio':False,'endpoint_id':'mac','protocol':1}
    def test_private_status_and_diagnostics_require_auth_and_expected_host(self):
        self.assertEqual(self.request('/api/desktop/status',auth=False)[0],403)
        self.assertEqual(self.request('/api/conversation/diagnostics',auth=False)[0],403)
        self.assertEqual(self.request('/api/desktop/status',host='unrelated.example')[0],403)
        status,data=self.request('/api/desktop/status');self.assertEqual(status,200);data=json.loads(data);self.assertEqual(data['spent_or_reserved_usd'],20.49657);self.assertFalse(data['cloud_audio'])
        self.assertNotIn('token',data)
        import hashlib
        from experiments.memory.native_voice import response_options
        options=response_options({'actual_speaker_id':'anonymous','people':{'anonymous':'Unknown'},'audience_ids':['anonymous']},{'facts':[]},'status-check')
        self.assertEqual(data['reply_prompt_sha256'],hashlib.sha256(options['instructions'].encode()).hexdigest())
    def test_assets_do_not_require_credentials_but_only_allowlist_is_served(self):
        self.assertEqual(self.request('/',auth=False)[0],200)
        self.assertIn(b'tavi-capture',self.request('/capture.js',auth=False)[1])
        self.assertEqual(self.request('/.env')[0],404);self.assertEqual(self.request('/api/command',{})[0],404)
    def test_explicit_consent_is_required_before_base_start(self):
        for key in self.consent():
            body=self.consent();body.pop(key)
            self.assertEqual(self.request('/api/conversation/start',body)[0],400)
        self.assertEqual(self.calls,[])
        self.assertEqual(self.request('/api/conversation/start',self.consent())[0],200);self.assertEqual(len(self.calls),1)
    def test_wrong_origin_endpoint_version_and_retention_fail_closed(self):
        self.assertEqual(self.request('/api/conversation/start',self.consent(),origin='https://unrelated.example')[0],403)
        for update in ({'endpoint_id':'pi'},{'protocol':2},{'retain_audio':True},{'adult':False},{'local_audio_only':False}):
            self.assertEqual(self.request('/api/conversation/start',{**self.consent(),**update})[0],400)
        self.assertEqual(self.calls,[])
    def test_drive_key_and_offline_choices_are_enforced(self):
        self.ready['ready']=False;self.assertEqual(self.request('/api/conversation/start',self.consent())[0],400)
        self.ready['ready']=True;self.ready['cloud_key']=False;self.assertEqual(self.request('/api/conversation/start',self.consent())[0],400)
        self.assertEqual(self.request('/api/conversation/start',{**self.consent(),'online':False})[0],200)
    def test_pause_requires_auth_and_does_not_terminate_core(self):
        self.assertEqual(self.request('/api/desktop/pause',{},auth=False)[0],403);self.assertEqual(self.calls,[])
        self.assertEqual(self.request('/api/desktop/pause',{})[0],200);self.assertEqual(self.calls,['pause'])
        self.assertEqual(self.request('/api/desktop/status')[0],200)

    def test_saved_feedback_is_explicit_local_and_private(self):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp, patch('tavi.mac_service.ROOT',Path(tmp)):
            self.assertEqual(self.request('/api/desktop/save-review',{'kind':'wrong'})[0],400)
            self.assertFalse((Path(tmp)/'.tavi/mac/reviews').exists())
            body={'kind':'paprika_mac_adult_check','real_audio_retained':False,'result':'problem','note':'Controlled feedback only'}
            self.assertEqual(self.request('/api/desktop/save-review',body,auth=False)[0],403)
            self.assertEqual(self.request('/api/desktop/save-review',body)[0],200)
            files=list((Path(tmp)/'.tavi/mac/reviews').glob('*.json'));self.assertEqual(len(files),1)
            self.assertEqual(files[0].stat().st_mode&0o777,0o600);self.assertEqual(json.loads(files[0].read_text()),body)


class CompanionTextTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_reference_has_empty_memory_and_anonymous_role(self):
        from tavi.companion_text import CompanionText
        calls=[]
        class Ref:
            async def connect(self):calls.append('connect')
            async def close(self):calls.append('close')
            async def stream_text(self,task,evidence,case):
                calls.append((task,evidence));yield 'Hello.';self.last_result={'status':'completed','text':'Hello.'}
        p=CompanionText(None,reference_factory=lambda _:Ref())
        output=[x async for x in p.stream_reply([{'role':'user','content':'Tell me a story.'}])]
        await p.close()
        self.assertEqual(output,['Hello.']);self.assertEqual(calls[1][1],{'facts':[]});self.assertEqual(calls[1][0]['actual_speaker_id'],'anonymous');self.assertFalse(p.memory_enabled);self.assertEqual(calls[-1],'close')
    async def test_incomplete_native_output_never_exhausts_successfully(self):
        from tavi.companion_text import CompanionText
        class Ref:
            async def connect(self):pass
            async def close(self):self.closed=True
            async def stream_text(self,*args):yield 'Hello.';self.last_result={'status':'incomplete','text':'Hello.'}
        ref=Ref();p=CompanionText(None,reference_factory=lambda _:ref)
        with self.assertRaises(ValueError):
            async for _ in p.stream_reply([{'role':'user','content':'hi'}]):pass
        await p.close();self.assertTrue(ref.closed)
    async def test_close_prevents_new_reply_without_connecting(self):
        from tavi.companion_text import CompanionText
        p=CompanionText(None,reference_factory=lambda _:self.fail('No connection expected'));await p.close()
        with self.assertRaises(ValueError):
            async for _ in p.stream_reply([{'role':'user','content':'hi'}]):pass


class ExistingBudgetTests(unittest.TestCase):
    def test_missing_or_empty_budget_cannot_be_silently_recreated(self):
        import sqlite3
        from pathlib import Path
        from tavi.storage import Store
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'ledger.sqlite3'
            with self.assertRaises(sqlite3.OperationalError):Store(p,must_exist=True)
            self.assertFalse(p.exists());p.touch()
            with self.assertRaises(ValueError):Store(p,must_exist=True)
    def test_existing_budget_preserves_unsettled_reservations_across_strict_reopen(self):
        from pathlib import Path
        from tavi.storage import Store
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'ledger.sqlite3';s=Store(p);s.reserve('pending',100,1000);s.close()
            s=Store(p,must_exist=True);self.assertEqual(s.used_micro_usd(),100)
            with self.assertRaises(ValueError):s.reserve('new',100,150)
            s.close()
