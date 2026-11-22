"""Guided local listening feedback; no microphone or inference endpoint."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from experiments.memory.runtime import ROOT,SSD,require_ssd

MANIFEST=ROOT/'experiments/memory/voice-continuity-preview-v1.json'
RATINGS={'both_good','a_smoother','b_smoother','neither'}
PACE_RATINGS={'acceptable','borderline','too_slow'}
PACE_DECISIONS={'pilot_with_limits','timing_first','discuss'}

def ratings_for(data, example):
    if data.get('review_type') == 'pace':
        return PACE_DECISIONS if example.get('decision') else PACE_RATINGS
    return RATINGS

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def validate(body,data,sha):
    if not isinstance(body,dict) or set(body)!={'id','manifest_sha256','completed','reviews'}:
        raise ValueError('The feedback could not be read. Try saving again.')
    if not isinstance(body['id'],str) or not re.fullmatch(r'[a-f0-9-]{36}',body['id']):raise ValueError('Reload this review before saving.')
    if body['manifest_sha256']!=sha:raise ValueError('The samples changed. Reload to hear the current examples.')
    expected={f"{e['id']}:{v['id']}" for e in data['examples'] for v in e['variants']}
    if (not isinstance(body['completed'],list) or any(not isinstance(x,str) for x in body['completed'])
            or len(body['completed'])!=len(expected) or set(body['completed'])!=expected):
        raise ValueError('Finish listening to each required clip before saving.')
    if not isinstance(body['reviews'],dict) or set(body['reviews'])!={e['id'] for e in data['examples']}:
        raise ValueError('Review each reply before saving.')
    for example in data['examples']:
        review=body['reviews'][example['id']]
        if not isinstance(review,dict) or set(review)!={'rating','notes'}:raise ValueError('The review could not be read.')
        if not isinstance(review['notes'],str) or len(review['notes'])>4000:raise ValueError('Keep each note below 4,000 characters.')
        if review['rating'] is not None and review['rating'] not in ratings_for(data,example):raise ValueError('Choose a listed response.')
        if review['rating'] is None and not review['notes'].strip():raise ValueError('Choose a response or write a note for each reply.')


def serve(port,qa=False,manifest=MANIFEST):
    require_ssd();data=json.loads(manifest.read_text());sha=digest(manifest)
    if digest(Path(data['source_run'])/'observations.json')!=data['source_sha256']:raise ValueError('Source evidence changed')
    assets={}
    for e in data['examples']:
        for v in e['variants']:
            p=Path(v['audio_path']).resolve();p.relative_to((SSD/'previews').resolve())
            if digest(p)!=v['audio_sha256']:raise ValueError('Audio evidence changed')
            assets[f"/audio/{e['id']}-{v['id']}.wav"]=p
    directory=ROOT/'.tavi/qa/voice-continuity' if qa else SSD/'owner-reviews/voice-continuity'
    directory.mkdir(parents=True,exist_ok=True);token=secrets.token_urlsafe(32)
    hosts={f'127.0.0.1:{port}',f'localhost:{port}'}
    pace=data.get('review_type')=='pace'
    page='conversation-pace.html' if pace else 'voice-continuity.html'
    script='conversation-pace.js' if pace else 'voice-continuity.js'
    public={'manifest_sha256':sha,'token':token,'qa':qa,'focus':data.get('focus'),'examples':[
        {**{k:v for k,v in e.items() if k!='variants'},'variants':[
            {'id':v['id'],'duration_ms':v['duration_ms']} for v in e['variants']]} for e in data['examples']]}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,status,value,kind='application/json'):
            raw=json.dumps(value).encode() if kind=='application/json' else value
            self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(raw)))
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; media-src 'self' blob:; object-src 'none'; frame-ancestors 'none'")
            self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            if self.headers.get('Host') not in hosts:return self.send(403,{'error':'Use the local review page.'})
            path=self.path.split('?')[0]
            if path=='/api/examples':return self.send(200,public)
            if path in assets:
                try:return self.send(200,assets[path].read_bytes(),'audio/wav')
                except OSError:return self.send(503,{'error':'Reconnect the external drive, then retry playback.'})
            for url,name,kind in [('/',page,'text/html; charset=utf-8'),('/'+script,script,'text/javascript')]:
                if path==url:return self.send(200,(ROOT/'tavi/web'/name).read_bytes(),kind)
            self.send(404,{'error':'Page not found.'})
        def do_POST(self):
            if (self.path!='/save' or self.headers.get('Host') not in hosts
                    or self.headers.get('Origin') not in {'http://'+h for h in hosts}
                    or self.headers.get('X-Review-Token')!=token):return self.send(403,{'error':'Reload this local review page.'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=25000:raise ValueError('The feedback is too large.')
                body=json.loads(self.rfile.read(size));validate(body,data,sha)
                record={**body,'kind':data['kind'],'scope':data['scope'],'qa':qa,
                    'saved_utc':datetime.now(timezone.utc).isoformat(),'source_run':data['source_run'],
                    'implementation_sha256':{str(p.relative_to(ROOT)):digest(p) for p in [Path(__file__),ROOT/'tavi/web'/page,ROOT/'tavi/web'/script]}}
                raw=json.dumps(record,indent=2).encode();name=body['id']+'-'+hashlib.sha256(raw).hexdigest()[:16]+'.json'
                fd,tmp=tempfile.mkstemp(dir=directory,prefix='.pending-')
                with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
                os.replace(tmp,directory/name);self.send(200,{'saved':True})
            except (ValueError,TypeError,KeyError) as exc:self.send(400,{'error':str(exc)})
            except OSError:self.send(503,{'error':'Reconnect the external drive and press Save again. Your answers remain on this page.'})
    print(json.dumps({'url':f'http://127.0.0.1:{port}/','qa':qa,'microphone':False,'inference':False}),flush=True)
    ThreadingHTTPServer(('127.0.0.1',port),Handler).serve_forever()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8773);parser.add_argument('--qa',action='store_true')
    parser.add_argument('--manifest',type=Path,default=MANIFEST)
    args=parser.parse_args();serve(args.port,args.qa,args.manifest)
