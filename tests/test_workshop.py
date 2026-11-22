import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
from tavi.storage import Store
from tavi.workshop import PreviewOwner,budget,probe,handler


class Child:
    def __init__(self,dead=False,timeout=False):self.dead=dead;self.timeout=timeout;self.terminated=0;self.killed=0
    def poll(self):return 1 if self.dead else None
    def terminate(self):self.terminated+=1
    def kill(self):self.killed+=1;self.dead=True
    def wait(self,timeout):
        if self.timeout and not self.killed:raise subprocess.TimeoutExpired('controlled',timeout)
        self.dead=True


class OwnerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
    def test_existing_recognized_setup_is_never_restarted_or_owned(self):
        calls=[];owner=PreviewOwner(self.root,inspect=lambda n:{'reachable':True,'recognized':True,'ready':False},popen=lambda *a,**k:calls.append(a))
        self.assertFalse(owner.ensure('adult')['ready']);owner.close();self.assertEqual(calls,[])
    def test_foreign_port_and_invalid_service_refused_without_spawn(self):
        calls=[];owner=PreviewOwner(self.root,inspect=lambda n:{'reachable':True,'recognized':False},popen=lambda *a,**k:calls.append(a))
        for service in ['adult','memory','cloud',{},None]:
            with self.assertRaises(ValueError):owner.ensure(service)
        self.assertEqual(calls,[])
    def test_only_selected_known_child_is_started_and_closed(self):
        states=iter([{'reachable':False,'recognized':False},{'reachable':True,'recognized':True,'ready':True}]);calls=[];child=Child()
        def popen(args,**kwargs):calls.append(args);return child
        owner=PreviewOwner(self.root,inspect=lambda n:next(states),popen=popen)
        self.assertTrue(owner.ensure('adventure')['ready']);owner.close()
        self.assertIn('tavi.adventure_preview',calls[0]);self.assertNotIn('tavi.speaker_setup',calls[0])
        self.assertEqual(child.terminated,1);self.assertEqual(child.killed,0)
    def test_failed_start_is_reported_and_shutdown_only_escalates_owned_child(self):
        child=Child(dead=True);owner=PreviewOwner(self.root,inspect=lambda n:{'reachable':False,'recognized':False},popen=lambda *a,**k:child)
        with self.assertRaisesRegex(ValueError,'could not start'):owner.ensure('adult')
        owner.close();self.assertEqual(child.terminated,0)
        slow=Child(timeout=True);owner.children['adventure']=slow;owner.close()
        self.assertEqual(slow.terminated,1);self.assertEqual(slow.killed,1)


class HealthTests(unittest.TestCase):
    def test_budget_is_read_only_and_missing_ledger_is_not_created(self):
        with tempfile.TemporaryDirectory() as d,patch('tavi.workshop.ROOT',Path(d)):
            self.assertEqual(budget(),{'available':False});self.assertFalse((Path(d)/'.tavi').exists())
            path=Path(d)/'.tavi/simulation/simulation.sqlite3';path.parent.mkdir(parents=True)
            store=Store(path);store.reserve('uncertain',50_000,25_000_000);store.close()
            before=hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(budget(),{'available':True,'spent_reserved_usd':.05,'cap_usd':25})
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)

    def test_probe_never_follows_redirect_or_uses_proxy(self):
        hits=[]
        class Trap(BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_GET(self):hits.append(True);self.send_response(200);self.end_headers()
        trap=ThreadingHTTPServer(('127.0.0.1',0),Trap);tt=threading.Thread(target=trap.serve_forever,daemon=True);tt.start()
        class Redirect(BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_GET(self):self.send_response(302);self.send_header('Location',f'http://127.0.0.1:{trap.server_port}/');self.end_headers()
        server=ThreadingHTTPServer(('127.0.0.1',0),Redirect);st=threading.Thread(target=server.serve_forever,daemon=True);st.start()
        try:
            with patch.dict('tavi.workshop.SERVICES',{'adventure':{'port':server.server_port,'path':'/api/health'}}),patch.dict('os.environ',{'http_proxy':'http://invalid.example:1','HTTP_PROXY':'http://invalid.example:1'}):
                result=probe('adventure');self.assertTrue(result['reachable']);self.assertFalse(result['recognized']);self.assertNotIn('url',result)
            self.assertEqual(hits,[])
        finally:server.shutdown();server.server_close();st.join();trap.shutdown();trap.server_close();tt.join()

    def test_hub_http_requires_local_origin_and_can_only_prepare_allowed_pages(self):
        calls=[]
        class Owner:
            def ensure(self,name):
                if name not in ('adult','adventure'):raise ValueError('Known preview only')
                calls.append(name);return {'recognized':True,'ready':True}
        server=ThreadingHTTPServer(('127.0.0.1',0),lambda *_:None);server.RequestHandlerClass=handler(Owner(),server.server_port)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base=f'http://127.0.0.1:{server.server_port}'
        def post(body,origin=None):
            headers={'Content-Type':'application/json'}
            if origin:headers['Origin']=origin
            req=urllib.request.Request(base+'/api/prepare',data=json.dumps(body).encode(),headers=headers)
            try:
                with urllib.request.urlopen(req,timeout=2) as r:return r.status
            except urllib.error.HTTPError as r:return r.code
        try:
            with urllib.request.urlopen(base,timeout=2) as r:self.assertIn('microphone=()',r.headers['Permissions-Policy']);self.assertIn(b'Welcome back',r.read())
            self.assertEqual(post({'service':'adult'}),403);self.assertEqual(post({'service':'adult'},'https://unrelated.example'),403)
            self.assertEqual(calls,[]);self.assertEqual(post({'service':'memory'},base),400)
            self.assertEqual(post({'service':'adventure'},base),200);self.assertEqual(calls,['adventure'])
        finally:server.shutdown();server.server_close();thread.join()
