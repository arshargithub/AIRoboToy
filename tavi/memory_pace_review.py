"""Local, guided pace-target illustration; no microphone or inference path."""
import argparse,hashlib,json,os,re,secrets,tempfile
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from experiments.memory.runtime import ROOT,SSD,require_ssd

MANIFEST=ROOT/'experiments/memory/pace-preview-v1.json'
DECISIONS={'allow_five_for_memory','keep_three','unsure'}

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def validate_review(body,data,manifest_sha):
    required={'id','manifest_sha256','completed','decision','notes'}
    if not isinstance(body,dict) or set(body)!=required:raise ValueError('The feedback could not be read. Please try again.')
    if not isinstance(body['id'],str) or not re.fullmatch(r'[a-f0-9-]{36}',body['id']):raise ValueError('Invalid review session. Reload to try again.')
    if body['manifest_sha256']!=manifest_sha:raise ValueError('The examples changed. Reload before saving.')
    expected={f"{e['id']}:{ms}" for e in data['examples'] for ms in data['waits_ms']}
    if not isinstance(body['completed'],list) or len(body['completed'])!=len(expected) or set(body['completed'])!=expected:
        raise ValueError('Play both waits for each example before choosing.')
    if body['decision'] not in DECISIONS:raise ValueError('Choose a next-prototype target.')
    if not isinstance(body['notes'],str) or len(body['notes'])>4000:raise ValueError('Keep the note below 4,000 characters.')
    return True

def serve(port,qa=False):
    require_ssd();data=json.loads(MANIFEST.read_text());digest=sha(MANIFEST)
    if sha(Path(data['source_run'])/'observations.json')!=data['source_sha256']:raise ValueError('Source evidence changed')
    assets={}
    for e in data['examples']:
        p=Path(e['audio_path']).resolve();p.relative_to((SSD/'previews').resolve())
        if sha(p)!=e['audio_sha256']:raise ValueError('Preview audio changed')
        assets['/audio/'+e['id']+'.wav']=p
    directory=(ROOT/'.tavi/qa/memory-pace') if qa else SSD/'owner-reviews/memory-pace'
    directory.mkdir(parents=True,exist_ok=True);token=secrets.token_urlsafe(32)
    hosts={f'127.0.0.1:{port}',f'localhost:{port}'}
    public={**data,'manifest_sha256':digest,'token':token,'qa':qa,
            'examples':[{k:v for k,v in e.items() if k not in ['audio_path','local_synthesis_ms']} for e in data['examples']]}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def send(self,status,value,kind='application/json'):
            raw=json.dumps(value).encode() if kind=='application/json' else value
            self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'")
            self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            if self.headers.get('Host') not in hosts:return self.send(403,{'error':'Use the local page.'})
            path=self.path.split('?')[0]
            if path=='/api/examples':return self.send(200,public)
            if path in assets:return self.send(200,assets[path].read_bytes(),'audio/wav')
            for url,name,kind in [('/','memory-pace.html','text/html; charset=utf-8'),('/memory-pace.js','memory-pace.js','text/javascript')]:
                if path==url:return self.send(200,(ROOT/'tavi/web'/name).read_bytes(),kind)
            self.send(404,{'error':'Page not found.'})
        def do_POST(self):
            if (self.path!='/save' or self.headers.get('Host') not in hosts
                or self.headers.get('Origin') not in {'http://'+h for h in hosts}
                or self.headers.get('X-Review-Token')!=token):return self.send(403,{'error':'Reload this local review page.'})
            try:
                n=int(self.headers.get('Content-Length','0'))
                if not 0<n<=20000:raise ValueError('The feedback is too large.')
                body=json.loads(self.rfile.read(n));validate_review(body,data,digest)
                record={**body,'kind':data['kind'],'scope':data['scope'],'qa':qa,'source_run':data['source_run'],'source_sha256':data['source_sha256'],
                        'saved_utc':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
                        'implementation_sha256':{str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__),ROOT/'tavi/web/memory-pace.js',ROOT/'tavi/web/memory-pace.html']}}
                raw=json.dumps(record,indent=2).encode();name=body['id']+'-'+hashlib.sha256(raw).hexdigest()[:16]+'.json'
                fd,tmp=tempfile.mkstemp(dir=directory,prefix='.pending-')
                with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
                os.replace(tmp,directory/name);self.send(200,{'saved':True,'id':body['id']})
            except (ValueError,TypeError,KeyError) as exc:self.send(400,{'error':str(exc)})
            except OSError:self.send(503,{'error':'The external drive could not save this. Reconnect it and press Save again; your answers remain on this page.'})
    print(json.dumps({'url':f'http://127.0.0.1:{port}/','qa':qa,'microphone':False,'inference':False}),flush=True)
    ThreadingHTTPServer(('127.0.0.1',port),Handler).serve_forever()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8771);p.add_argument('--qa',action='store_true');a=p.parse_args();serve(a.port,a.qa)
