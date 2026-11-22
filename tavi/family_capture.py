"""Three guided family collection links; all processing/storage is local."""
import argparse
import json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from importlib.metadata import version
from pathlib import Path
import signal
import threading
from urllib.parse import urlsplit,parse_qs
from tavi.family_collection import FamilyCollection,PEOPLE,PROMPTS,CONSENT
from tavi.speaker_profile import ROOT,require_drive
from tavi.speaker_process import SpeakerProcess
from tavi.experiment_workflow import begin,audit,finish,digest
from experiments.memory.runtime import SSD


def bind(body):
    child=PEOPLE[body['person_id']]['child']
    existing=[json.loads(p.read_text()) for p in (SSD/'runs/scored/FAMILY-VOICE-COLLECTION-01').glob('*/run.json')]
    if len(existing)>=6 or sum(r.get('consent',{}).get('subject_id')==body['person_id'] for r in existing)>=2:
        raise ValueError('This collection trial has reached its new-profile limit. Earlier samples are kept; local review is needed before another separate collection.')
    consent={'adult':True,'recording':True,'cloud':False,'processing':'local-only','subject_id':body['person_id'],
        'subject_is_child':child,'subject_willing':True,'alone':True,'supervised':child,'own_voice':not child,'retain_audio':body['retain_audio']}
    folder,_=begin(ROOT/'experiments/speaker-id/family-collection-protocol-v1.json',run_root=SSD/'runs/scored',consent=consent)
    audit(folder);return folder


def seal(collection,token,person):
    with collection.lock:
        folder,draft=collection.folder(token,person);run=Path(draft['workflow_run'])
        if json.loads((run/'run.json').read_text())['state']=='finished':return
        profile=json.loads((folder/'profile.json').read_text())
        metrics={'reviewed_samples':len(profile['clips']),'subject_bound':profile['person_id']==person,
            'candidate_only':not profile['recognition_enabled'] and not profile['authorizes_personal_memory'] and profile['threshold'] is None,
            'local_only':profile['local_only'],'cloud_requests':0,'additional_api_usd':0.0}
        (run/'observations.json').write_text(json.dumps({'person_id':person,'metrics':metrics,'attempts':len(draft['attempts']),
            'excluded':sum(a['review']=='exclude' for a in draft['attempts']),'E4_accepted':False},indent=2)+'\n')
        artifacts=[folder/'profile.json',folder/'draft.json',run/'observations.json']+[folder/a['reference_file'] for a in draft['attempts'] if a.get('reference_file')]
        finish(run,metrics,artifacts=artifacts,completed=True)


def ready():
    require_drive()
    model=json.loads((ROOT/'experiments/speaker-id/model-manifest.json').read_text())
    if digest(model['path'])!=model['sha256']:raise ValueError('Local voice model changed. Keep samples; it needs review before recording.')
    for file in json.loads((ROOT/'experiments/speaker-id/model-assets.json').read_text())['files']:
        if digest(file['path'])!=file['sha256']:raise ValueError('Local voice files changed. Keep samples; setup needs review.')
    expected=json.loads((ROOT/'experiments/speaker-id/environment.json').read_text())['versions']
    if any(version(k)!=v for k,v in expected.items()):raise ValueError('The local voice packages changed. Setup needs review before recording.')


def handler(collection,port):
    hosts={f'127.0.0.1:{port}',f'localhost:{port}'}
    static={'/family-capture.js':('family-capture.js','text/javascript'),'/family-capture.css':('family-capture.css','text/css'),
        '/adventure-preview.css':('adventure-preview.css','text/css'),'/capture.js':('capture.js','text/javascript')}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def send(self,code,value,mime='application/json'):
            raw=value if isinstance(value,bytes) else json.dumps(value).encode()
            self.send_response(code)
            for k,v in {'Content-Type':mime,'Content-Length':str(len(raw)),'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
                'Permissions-Policy':'microphone=(self), camera=(), geolocation=()',
                'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; media-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"}.items():self.send_header(k,v)
            self.end_headers();self.wfile.write(raw)
        def subject(self):
            person=self.headers.get('X-Person-ID')
            if person not in PEOPLE:raise ValueError('Use the named link for Child One, Child Two or Adult Two.')
            return person
        def token(self):return self.headers.get('X-Collection-Session')
        def do_GET(self):
            if self.headers.get('Host') not in hosts:return self.send(403,{'error':'Local collection only'})
            path=urlsplit(self.path).path
            if path.strip('/') in PEOPLE:
                person=path.strip('/');raw=(ROOT/'tavi/web/family-capture.html').read_text().replace('@@PERSON@@',person).replace('@@NAME@@',PEOPLE[person]['name'])
                return self.send(200,raw.encode(),'text/html; charset=utf-8')
            if path in static:
                name,mime=static[path];return self.send(200,(ROOT/'tavi/web'/name).read_bytes(),mime)
            try:
                if path=='/api/health':return self.send(200,{'family_collection':True,'subjects':list(PEOPLE),'cloud':False,'recognition_enabled':False})
                if path.startswith('/prompts/') and path.endswith('.wav'):
                    pid=path.removeprefix('/prompts/').removesuffix('.wav')
                    if pid not in {p['id'] for p in PROMPTS}|{'practice'}:raise ValueError('Unknown question')
                    manifest=json.loads((ROOT/'experiments/speaker-id/family-prompt-audio-assets-v1.json').read_text())
                    entry=next(p for p in manifest['prompts'] if p['id']==pid);file=Path(entry['path'])
                    if not file.is_file() or digest(file)!=entry['sha256']:raise ValueError('Question audio unavailable')
                    return self.send(200,file.read_bytes(),'audio/wav')
                if path=='/api/setup':
                    person=parse_qs(urlsplit(self.path).query).get('person',[''])[0]
                    if person not in PEOPLE:raise ValueError('Open the dedicated link for this person.')
                    try:ready();available=True;message='Ready for local-only voice collection.'
                    except Exception:available=False;message='Connect the external drive and check again. If it is connected, local files or packages need review. No recording has begun.'
                    return self.send(200,{'person_id':person,**PEOPLE[person],'available':available,'message':message,
                        'consent':CONSENT,'prompts':PROMPTS,'cloud':False,'recognition_enabled':False})
                if path=='/api/state':return self.send(200,collection.state(self.token(),self.subject()))
                if path.startswith('/api/audio/'):
                    return self.send(200,collection.audio(self.token(),self.subject(),path.rsplit('/',1)[-1]),'audio/wav')
                self.send(404,{'error':'Not found'})
            except (ValueError,OSError):self.send(400,{'error':'This local collection could not be reopened. Check the drive and use this person’s original link. Earlier samples are kept.'})
        def do_POST(self):
            origin=self.headers.get('Origin')
            if self.headers.get('Host') not in hosts or origin not in {'http://'+h for h in hosts}:return self.send(403,{'error':'Use the button on this local collection page'})
            try:
                person=self.subject();size=int(self.headers.get('Content-Length','0'));path=urlsplit(self.path).path
                if not 0<=size<=256000:raise ValueError('Record one short turn at a time.')
                raw=self.rfile.read(size)
                if path=='/api/attempt':
                    if self.headers.get('Content-Type')!='application/octet-stream':raise ValueError('Expected a local mono voice recording.')
                    return self.send(200,collection.attempt(self.token(),person,self.headers.get('X-Attempt-ID'),self.headers.get('X-Prompt-ID'),raw,json.loads(self.headers.get('X-Capture-Settings','{}'))))
                if self.headers.get('Content-Type')!='application/json' or size>16000:raise ValueError('Choose one action on this page.')
                body=json.loads(raw)
                if not isinstance(body,dict):raise ValueError('Choose a collection action.')
                if path=='/api/begin':
                    if body.get('person_id')!=person:raise ValueError('This link belongs to a different person.')
                    return self.send(200,collection.begin(body,self.token()))
                if path=='/api/review':return self.send(200,collection.review(self.token(),person,body.get('choices'),body.get('attested')))
                if path=='/api/more':return self.send(200,collection.more(self.token(),person))
                if path=='/api/pause':return self.send(200,collection.pause(self.token(),person))
                if path=='/api/skip':return self.send(200,collection.skip(self.token(),person,body.get('id'),body.get('prompt_id'),body.get('sha')))
                if path=='/api/finish':
                    collection.finish(self.token(),person);seal(collection,self.token(),person)
                    return self.send(200,collection.state(self.token(),person))
                self.send(404,{'error':'Not found'})
            except (ValueError,TimeoutError) as error:self.send(400,{'error':str(error)})
            except Exception:self.send(503,{'error':'The local check or save could not finish. Microphone is off. Reconnect the drive and retry this step; earlier samples are kept.'})
    return Handler


def main():
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8783);args=p.parse_args()
    if not 1<=args.port<=65535:p.error('Invalid port')
    encoder=SpeakerProcess();collection=FamilyCollection(encoder=encoder,bind=bind)
    server=ThreadingHTTPServer(('127.0.0.1',args.port),handler(collection,args.port));server.daemon_threads=True
    def stop(*_):threading.Thread(target=server.shutdown,daemon=True).start()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,stop)
    print(f'Family local collection: http://127.0.0.1:{args.port}/childone /childtwo /adulttwo',flush=True)
    try:server.serve_forever()
    finally:server.server_close();encoder.close()


if __name__=='__main__':main()
