"""Separate adult-only local voice enrollment. No conversation/cloud clients."""
import json,signal,threading
from importlib.metadata import version,PackageNotFoundError
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from tavi.speaker_profile import Enrollment,PHRASES,ADULTS,CONSENT,ROOT,require_drive
from tavi.speaker_process import SpeakerProcess
from tavi.experiment_workflow import begin,audit,finish
from experiments.memory.runtime import SSD

def bind(body):
 folder,_=begin(ROOT/'experiments/speaker-id/adult-enroll-protocol-v1.json',run_root=SSD/'runs/scored',consent={'adult':True,'recording':True,'cloud':False,'retain_audio':body['retain_audio'],'person_id':body['person_id'],'voice_embedding_local':True})
 audit(folder);return folder

def seal(enroll,token):
 with enroll.lock:return _seal(enroll,token)

def _seal(enroll,token):
 folder,draft=enroll._folder(token);run=Path(draft['workflow_run']);record=json.loads((run/'run.json').read_text())
 if record['state']=='finished':return
 profile=json.loads((folder/'profile.json').read_text())
 metrics={'recordings_reviewed':len(draft['clips']),'same_model':len({c['model_sha256'] for c in draft['clips']})==1,'candidate_only':not profile['recognition_enabled'] and not profile['authorizes_personal_memory'] and profile['threshold'] is None,'minimum_voiced_seconds':min(c['quality']['voiced_seconds'] for c in draft['clips']),'cloud_requests':0,'additional_api_usd':0.0}
 (run/'observations.json').write_text(json.dumps({'profile_id':folder.name,'person_id':draft['person_id'],'retained_audio':draft['retain_audio'],'metrics':metrics,'recognition_enabled':False,'threshold_selected':False,'E4_accepted':False},indent=2)+'\n')
 artifacts=[folder/'profile.json',folder/'draft.json',run/'observations.json']+[folder/c['reference_file'] for c in draft['clips'] if 'reference_file' in c]
 finish(run,metrics,artifacts=artifacts,completed=True)

def handler(enroll,port):
 hosts={f'127.0.0.1:{port}',f'localhost:{port}'}
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*_):pass
  def send(self,status,value,mime='application/json'):
   raw=value if isinstance(value,bytes) else json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(raw)
  def token(self):return self.headers.get('X-Enrollment-Session')
  def do_GET(self):
   if self.headers.get('Host') not in hosts:return self.send(403,{'error':'Localhost only'})
   path=urlsplit(self.path).path
   assets={'/':('speaker-setup.html','text/html; charset=utf-8'),'/speaker-setup.js':('speaker-setup.js','text/javascript'),'/capture.js':('capture.js','text/javascript')}
   if path in assets:
    file,mime=assets[path];return self.send(200,(ROOT/'tavi/web'/file).read_bytes(),mime)
   try:
    if path=='/api/setup':
     try:
      require_drive()
      from tavi.experiment_workflow import digest
      model=json.loads((ROOT/'experiments/speaker-id/model-manifest.json').read_text())
      if digest(model['path'])!=model['sha256'] or not (ROOT/'.tavi/models/silero_vad.onnx').is_file():raise ValueError('Local voice model files are unavailable. Reconnect the drive and check again.')
      expected=json.loads((ROOT/'experiments/speaker-id/environment.json').read_text())['versions']
      if any(version(name)!=value for name,value in expected.items()):raise ValueError('The local voice packages changed. Keep recordings safe; setup needs review before recording.')
      available=True;message='Ready for local-only adult enrollment.'
     except ValueError as e:available=False;message=str(e)
     except (OSError,PackageNotFoundError):available=False;message='Local voice files or packages are unavailable. Connect the external drive and check again. Existing recordings are kept.'
     return self.send(200,{'available':available,'message':message,'adults':ADULTS,'phrases':PHRASES,'consent':CONSENT,'recognition_enabled':False,'cloud':False})
    if path=='/api/state':return self.send(200,enroll.state(self.token()))
   except (OSError,ValueError):return self.send(400,{'error':'This local session could not be reopened. Reconnect the drive and Retry, or start a separate new profile. Existing files are kept.'})
   self.send(404,{'error':'Not found'})
  def do_POST(self):
   origin=self.headers.get('Origin')
   if self.headers.get('Host') not in hosts or (origin and origin not in {'http://'+h for h in hosts}):return self.send(403,{'error':'Local origin required'})
   try:
    size=int(self.headers.get('Content-Length','0'))
    if not 0<size<=256000:raise ValueError('Recording is too large. Try one phrase at a time.')
    raw=self.rfile.read(size);path=urlsplit(self.path).path
    if path=='/api/preview':
     if self.headers.get('Content-Type')!='application/octet-stream':raise ValueError('Expected a local voice recording')
     return self.send(200,enroll.preview(self.token(),int(self.headers.get('X-Clip-Index','-1')),raw))
    if self.headers.get('Content-Type')!='application/json':raise ValueError('Expected a local enrollment choice')
    body=json.loads(raw)
    if not isinstance(body,dict):raise ValueError('Choose an enrollment action')
    if path=='/api/begin':return self.send(200,enroll.begin(body,self.token()))
    if path=='/api/use':return self.send(200,enroll.use(self.token(),body.get('index'),body.get('sha'),body.get('capture_settings')))
    if path=='/api/finish':
     enroll.finish(self.token(),body.get('note',''));seal(enroll,self.token());return self.send(200,enroll.state(self.token()))
    self.send(404,{'error':'Unknown action'})
   except (ValueError,TimeoutError) as e:self.send(400,{'error':str(e)})
   except Exception:self.send(503,{'error':'Local save/check could not finish. Reconnect the external drive and Retry. Keep this page open; the recording is still here.'})
 return Handler

def main():
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8780);args=p.parse_args()
 if not 1<=args.port<=65535:p.error('Invalid port')
 encoder=SpeakerProcess();enroll=Enrollment(encoder=encoder,bind=bind);server=ThreadingHTTPServer(('127.0.0.1',args.port),handler(enroll,args.port));server.daemon_threads=True;server.service_actions=enroll.expire_previews
 def stop(*_):threading.Thread(target=server.shutdown,daemon=True).start()
 for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,stop)
 print(f'Adult local voice enrollment: http://127.0.0.1:{args.port}/',flush=True)
 try:server.serve_forever()
 finally:server.server_close();encoder.close()
if __name__=='__main__':main()
