"""Guided local preparation hub; no microphone, keys, models or inference."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
DRIVE=Path('/Volumes/MovieFactorySSD')
SERVICES={
    'adult':{'port':8780,'path':'/api/setup','module':'tavi.speaker_setup','title':'Adult voice setup'},
    'family':{'port':8783,'path':'/api/health','module':'tavi.family_capture','title':'Named family collection'},
    'adventure':{'port':8781,'path':'/api/health','module':'tavi.adventure_preview','title':'Adventure preview'}}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*_):return None


def probe(name,timeout=.6):
    cfg=SERVICES[name];url=f"http://127.0.0.1:{cfg['port']}"
    result={'reachable':False,'recognized':False,'ready':False}
    try:
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        with opener.open(url+cfg['path'],timeout=timeout) as response:
            raw=response.read(65537)
        if len(raw)>65536:raise ValueError('Oversized local status')
        data=json.loads(raw)
        result['reachable']=True
        if name=='adult':
            result['recognized']=(data.get('consent')=='adult-local-voice-enrollment-v1'
                                  and data.get('cloud') is False and data.get('recognition_enabled') is False)
            result['ready']=result['recognized'] and data.get('available') is True
        elif name=='adventure':
            result['recognized']=(data.get('preview') is True and data.get('microphone') is False
                                 and data.get('models') is False and data.get('cloud') is False and data.get('real_profiles') is False)
            result['ready']=result['recognized']
        else:
            result['recognized']=(data.get('family_collection') is True and data.get('subjects')==['childone','childtwo','adulttwo']
                                  and data.get('cloud') is False and data.get('recognition_enabled') is False)
            result['ready']=result['recognized']
    except Exception:pass
    # A broken/unrecognized occupied port must not trigger a replacement.
    if not result['reachable']:
        try:
            with socket.create_connection(('127.0.0.1',cfg['port']),timeout=.2):result['reachable']=True
        except OSError:pass
    if result['recognized']:result['url']=url+'/'
    return result


def budget():
    path=ROOT/'.tavi/simulation/simulation.sqlite3'
    if not path.is_file():return {'available':False}
    try:
        db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=.1)
        try:used=db.execute('SELECT COALESCE(SUM(COALESCE(actual,reserved)),0) FROM spending').fetchone()[0]
        finally:db.close()
        if type(used) is not int or used<0:return {'available':False}
        return {'available':True,'spent_reserved_usd':used/1e6,'cap_usd':25}
    except sqlite3.Error:return {'available':False}


def status():
    with ThreadPoolExecutor(max_workers=3) as pool:
        services=dict(zip(SERVICES,pool.map(probe,SERVICES)))
    mounted=DRIVE.is_mount()
    return {'mode':'preparation_only','this_page_uses_microphone':False,'live_identity_enabled':False,
            'household_memory_enabled':False,'drive_connected':mounted,
            'voice_model_file_present':mounted and (DRIVE/'PaprikaVoice/models/3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx').is_file(),
            'budget':budget(),'services':services}


class PreviewOwner:
    def __init__(self,root=ROOT,*,inspect=probe,popen=subprocess.Popen):
        self.root=Path(root);self.inspect=inspect;self.popen=popen;self.children={};self.lock=threading.Lock()
    def ensure(self,name):
        if not isinstance(name,str) or name not in SERVICES:raise ValueError('Choose one of the known local preparation pages')
        with self.lock:
            found=self.inspect(name)
            if found['recognized']:return found
            if found['reachable']:raise ValueError('This address is in use but could not be verified. Its process has been left running. Wait a moment, then Check again; if this persists it needs developer review.')
            previous=self.children.get(name)
            if previous and previous.poll() is None:raise ValueError('This setup is still starting. Wait a moment, then Check again.')
            cfg=SERVICES[name];logs=self.root/'.tavi';logs.mkdir(exist_ok=True)
            log=(logs/('workshop-'+name+'-'+uuid4().hex+'.log')).open('ab')
            try:child=self.popen([sys.executable,'-m',cfg['module'],'--port',str(cfg['port'])],cwd=self.root,stdout=log,stderr=log,start_new_session=True)
            finally:log.close()
            self.children[name]=child
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                if child.poll() is not None:raise ValueError('The local setup could not start. Existing files are kept. Check again; no recording has begun.')
                found=self.inspect(name)
                if found['recognized']:return found
                if found['reachable']:raise ValueError('A different app took this address. It has been left alone; no setup was opened.')
                time.sleep(.08)
            raise ValueError('The local setup is taking longer to start. Wait a moment, then Check again. No recording has begun.')
    def close(self):
        with self.lock:
            for child in self.children.values():
                if child.poll() is None:
                    child.terminate()
                    try:child.wait(timeout=3)
                    except subprocess.TimeoutExpired:child.kill();child.wait(timeout=2)
            self.children.clear()


def handler(owner,port):
    hosts={f'127.0.0.1:{port}',f'localhost:{port}'}
    assets={'/':('workshop.html','text/html; charset=utf-8'),'/workshop.js':('workshop.js','text/javascript'),'/workshop.css':('workshop.css','text/css')}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def send(self,code,value,mime='application/json'):
            raw=value if isinstance(value,bytes) else json.dumps(value).encode()
            self.send_response(code)
            for key,val in {'Content-Type':mime,'Content-Length':str(len(raw)),'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
                'Permissions-Policy':'microphone=(), camera=(), geolocation=()',
                'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; media-src 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"}.items():self.send_header(key,val)
            self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            if self.headers.get('Host') not in hosts:return self.send(403,{'error':'Local preparation page only'})
            if self.path in assets:
                name,mime=assets[self.path];return self.send(200,(ROOT/'tavi/web'/name).read_bytes(),mime)
            if self.path=='/api/status':return self.send(200,status())
            self.send(404,{'error':'Not found'})
        def do_POST(self):
            if self.headers.get('Host') not in hosts or self.headers.get('Origin') not in {'http://'+h for h in hosts}:
                return self.send(403,{'error':'Use the button on the local workshop page'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if self.path!='/api/prepare' or self.headers.get('Content-Type')!='application/json' or not 0<size<=256:raise ValueError('Choose a preparation action on this page')
                body=json.loads(self.rfile.read(size))
                if not isinstance(body,dict):raise ValueError('Choose a preparation action')
                found=owner.ensure(body.get('service'))
                self.send(200,found)
            except ValueError as error:self.send(400,{'error':str(error)})
            except Exception:self.send(503,{'error':'The local page could not be prepared. Existing files are kept. Check again; no recording or online job was started.'})
    return Handler


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8782);parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    if args.check:print(json.dumps(status(),indent=2));return
    if not 1<=args.port<=65535:parser.error('Invalid port')
    owner=PreviewOwner();server=ThreadingHTTPServer(('127.0.0.1',args.port),handler(owner,args.port));server.daemon_threads=True
    def stop(*_):threading.Thread(target=server.shutdown,daemon=True).start()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,stop)
    print(f'Paprika workshop: http://127.0.0.1:{args.port}/',flush=True)
    try:server.serve_forever()
    finally:server.server_close();owner.close()


if __name__=='__main__':main()
