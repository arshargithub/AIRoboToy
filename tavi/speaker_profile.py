"""Local candidate voice enrollment; never authorizes live identity or memory.

Embeddings bind to the exact model hash. Personal recordings/profiles live only
on the mounted external drive. Enrollment consistency is not verification.
"""
import hashlib,json,os,re,secrets,threading,time,wave
from datetime import datetime,timezone
from io import BytesIO
from pathlib import Path
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
VOICE=Path('/Volumes/MovieFactorySSD/PaprikaVoice')
ADULTS={'adultone':'Adult One','adulttwo':'Adult Two'}
PHRASES=[
'Paprika, today I am making a small paper boat for a rainy afternoon.',
'There are three bright cushions and a blanket beside the window.',
'I wonder what a friendly dragon would keep inside a secret box.',
'We could build a little bridge and see how much it can hold.',
'Some mornings I like to sit quietly before the day gets busy.',
'If we went to the park, we could look for birds in the trees.']
CONSENT='adult-local-voice-enrollment-v1'
def require_drive():
 if not VOICE.parent.is_mount() or not VOICE.is_dir():raise ValueError('Connect the external drive, then try again. This recording has not been saved yet.')
def stamp():return datetime.now(timezone.utc).isoformat()
def write_json(path,value):
 path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);tmp=path.with_name('.pending-'+uuid4().hex)
 try:
  fd=os.open(tmp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
  with os.fdopen(fd,'w') as out:json.dump(value,out,indent=2);out.write('\n');out.flush();os.fsync(out.fileno())
  os.replace(tmp,path)
 finally:
  if tmp.exists():tmp.unlink()
def wave_bytes(pcm):
 out=BytesIO()
 with wave.open(out,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(pcm)
 return out.getvalue()

class SpeakerEncoder:
 def __init__(self):self.extractor=None;self.vad=None;self.lock=threading.Lock()
 def prepare(self):
  require_drive()
  if self.extractor is not None:return
  import importlib.metadata as meta,sherpa_onnx
  self.manifest=json.loads((ROOT/'experiments/speaker-id/model-manifest.json').read_text());model=Path(self.manifest['path'])
  if meta.version('sherpa-onnx')!=self.manifest['runtime_version'] or hashlib.sha256(model.read_bytes()).hexdigest()!=self.manifest['sha256']:raise ValueError('The local voice model changed. Keep the saved recordings; model qualification must be checked.')
  cfg=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(model),num_threads=2,provider='cpu',debug=False)
  if not cfg.validate():raise ValueError('Local voice model is unavailable. Reconnect the external drive and try again.')
  self.extractor=sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
  from tavi.acoustics import Silero
  self.vad=Silero(ROOT/'.tavi/models/silero_vad.onnx',wake_backend='off')
 def encode(self,pcm):
  import numpy as np
  if not isinstance(pcm,bytes) or len(pcm)%2 or not 32000<=len(pcm)<=256000:raise ValueError('Keep this recording between one and eight seconds. Record the phrase again.')
  with self.lock:
   self.prepare();values=np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768
   rms=float(np.sqrt(np.mean(values*values)));clipped=float(np.mean(abs(values)>=.999))
   self.vad.reset();voiced=[]
   for start in range(0,len(pcm),1024):
    frame=pcm[start:start+1024].ljust(1024,b'\0')
    if self.vad.probability(frame)>=.5:voiced.append(start//2)
   seconds=len(voiced)*.032
   if seconds<2:raise ValueError('I need a little more clear speech. Read the whole phrase in your normal voice, then try again.')
   if rms<.003:raise ValueError('The recording is too quiet. Move a little closer and record again.')
   if clipped>.03:raise ValueError('The recording is distorted. Move a little farther away and record again.')
   start=max(0,voiced[0]-3840);end=min(len(values),voiced[-1]+512+3840)
   stream=self.extractor.create_stream();stream.accept_waveform(16000,values[start:end]);stream.input_finished()
   if not self.extractor.is_ready(stream):raise ValueError('Not enough clear voice. Try the phrase again.')
   vec=np.asarray(self.extractor.compute(stream),dtype=np.float32);norm=float(np.linalg.norm(vec))
   if vec.shape!=(self.extractor.dim,) or not np.isfinite(vec).all() or norm<1e-8:raise ValueError('The local voice check could not finish. Record this phrase again.')
   vec/=norm
   return {'embedding':vec.tolist(),'model_sha256':self.manifest['sha256'],'dimension':int(self.extractor.dim),'quality':{'duration_seconds':len(values)/16000,'voiced_seconds':seconds,'rms':rms,'clipped_fraction':clipped,'trim_start_sample':start,'trim_end_sample':end},'pcm_sha256':hashlib.sha256(pcm).hexdigest()}

class Enrollment:
 def __init__(self,root=VOICE/'enrollment',*,encoder=None,guard=require_drive,bind=None):
  self.root=Path(root);self.encoder=encoder or SpeakerEncoder();self.guard=guard;self.lock=threading.RLock();self.pending={};self.pending_at={};self.bind=bind
 def expire_previews(self):
  if not self.lock.acquire(blocking=False):return
  try:
   for token,at in list(self.pending_at.items()):
    if time.monotonic()-at>600:self.pending.pop(token,None);self.pending_at.pop(token,None)
  finally:self.lock.release()
 def _folder(self,token):
  if not isinstance(token,str) or not re.fullmatch(r'[a-f0-9]{32}\.[a-f0-9]{48}',token):raise ValueError('Start or resume enrollment first.')
  folder=self.root/token[:32];draft=json.loads((folder/'draft.json').read_text())
  if not secrets.compare_digest(draft['token_hash'],hashlib.sha256(token.encode()).hexdigest()):raise ValueError('This enrollment belongs to another session.')
  return folder,draft
 def state(self,token):
  self.guard();folder,draft=self._folder(token)
  sealed=not draft.get('workflow_run') or json.loads((Path(draft['workflow_run'])/'run.json').read_text())['state']=='finished'
  return {'person_id':draft['person_id'],'name':ADULTS[draft['person_id']],'retain_audio':draft['retain_audio'],'saved_clips':len(draft['clips']),'clip_hashes':[c['pcm_sha256'] for c in draft['clips']],'total_clips':6,'phrase':PHRASES[len(draft['clips'])] if len(draft['clips'])<6 else None,'complete':(folder/'profile.json').is_file() and sealed,'recognition_enabled':False}
 def begin(self,body,token=None):
  self.guard()
  if body.get('consent')!=CONSENT or body.get('adult_alone') is not True or body.get('processing')!='local-only' or body.get('person_id') not in ADULTS or type(body.get('retain_audio')) is not bool:raise ValueError('Choose the adult speaking, local-only processing, recording choice and adult consent before starting.')
  with self.lock:
   if token:
    state=self.state(token)
    if (state['person_id'],state['retain_audio'])!=(body['person_id'],body['retain_audio']):raise ValueError('Use the original person and recording choice to resume, or start a separate new profile.')
    return {'session':token,**state}
   if self.root.exists() and sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file())>256_000_000:raise ValueError('The local enrollment folder is full. Keep existing profiles; storage needs review before more recording.')
   token=uuid4().hex+'.'+secrets.token_hex(24);folder=self.root/token[:32]
   bound=self.bind(body) if self.bind else None
   self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
   write_json(folder/'draft.json',{'person_id':body['person_id'],'retain_audio':body['retain_audio'],'token_hash':hashlib.sha256(token.encode()).hexdigest(),'created_at':stamp(),'consent':CONSENT,'processing':'local-only','adult_alone':True,'workflow_run':str(bound) if bound else None,'clips':[]})
   return {'session':token,**self.state(token)}
 def preview(self,token,index,pcm):
  self.guard()
  with self.lock:
   folder,draft=self._folder(token)
   if type(index) is not int or index!=len(draft['clips']) or index>=6 or (folder/'profile.json').exists():raise ValueError('This phrase is already saved. Continue with the next phrase shown.')
   result=self.encoder.encode(pcm);self.pending[token]=(index,pcm,result);self.pending_at[token]=time.monotonic()
   return {'clear_voice':True,'pcm_sha256':result['pcm_sha256'],'quality':result['quality']}
 def use(self,token,index,sha,capture_settings=None):
  self.guard()
  settings=capture_settings or {}
  allowed={'audio_context_rate','requested_echo_cancellation','requested_noise_suppression','requested_auto_gain_control','actual_sampleRate','actual_channelCount','actual_echoCancellation','actual_noiseSuppression','actual_autoGainControl'}
  if not isinstance(settings,dict) or not set(settings)<=allowed or any(type(v) not in (int,bool) and not (k=='actual_echoCancellation' and v in ('all','remote-only')) for k,v in settings.items()):raise ValueError('Unexpected microphone settings; no device identifiers are saved.')
  with self.lock:
   folder,draft=self._folder(token)
   if type(index) is not int or not 0<=index<6:raise ValueError('Unknown phrase')
   if index<len(draft['clips']):
    if draft['clips'][index]['pcm_sha256']!=sha:raise ValueError('Saved phrase differs; it cannot be overwritten.')
    return self.state(token)
   pending=self.pending.get(token)
   if not pending or pending[0]!=index or pending[2]['pcm_sha256']!=sha:raise ValueError('Record and review this phrase before saving it.')
   _,pcm,result=pending
   if draft['retain_audio']:
    path=folder/f'clip-{index+1}-{sha[:12]}.wav'
    raw=wave_bytes(pcm)
    if path.exists() and path.read_bytes()!=raw:path=folder/f'clip-{index+1}-{sha[:12]}-recovered-{uuid4().hex}.wav'
    if not path.exists():
     temporary=folder/('.pending-audio-'+uuid4().hex)
     try:
      fd=os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
      with os.fdopen(fd,'wb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
      os.replace(temporary,path)
     finally:
      if temporary.exists():temporary.unlink()
    result={**result,'reference_file':path.name}
   draft['clips'].append({**result,'phrase':PHRASES[index],'at':stamp(),'browser_reported_capture_settings':settings});write_json(folder/'draft.json',draft);self.pending.pop(token,None);self.pending_at.pop(token,None)
   return self.state(token)
 def finish(self,token,note=''):
  if not isinstance(note,str) or len(note)>500:raise ValueError('Keep recording notes under 500 characters.')
  self.guard()
  with self.lock:
   folder,draft=self._folder(token)
   if len(draft['clips'])!=6:raise ValueError('Save all six phrases before saving the voice profile.')
   if (folder/'profile.json').exists():return self.state(token)
   import numpy as np
   hashes={c['model_sha256'] for c in draft['clips']};dimensions={c['dimension'] for c in draft['clips']}
   if len(hashes)!=1 or len(dimensions)!=1:raise ValueError('The model changed during enrollment. Keep these clips for review; do not combine the profiles.')
   for clip in draft['clips']:
    if 'reference_file' in clip:
     try:
      with wave.open(str(folder/clip['reference_file']),'rb') as w:
       valid=(w.getnchannels(),w.getsampwidth(),w.getframerate())==(1,2,16000) and hashlib.sha256(w.readframes(w.getnframes())).hexdigest()==clip['pcm_sha256']
     except (wave.Error,EOFError):valid=False
     if not valid:raise ValueError('A saved reference recording changed. Existing files are kept. Return to setup and start a separate new profile, or keep these files for review.')
   vectors=np.array([c['embedding'] for c in draft['clips']],dtype=np.float32)
   if not np.isfinite(vectors).all() or vectors.shape!=(6,next(iter(dimensions))):raise ValueError('Invalid local voice profile; keep the recordings for review.')
   centroid=vectors.mean(axis=0);norm=float(np.linalg.norm(centroid))
   if norm<1e-8:raise ValueError('Voice profile could not be combined. Keep the recordings for review.')
   centroid/=norm
   write_json(folder/'profile.json',{'schema_version':1,'profile_id':folder.name,'person_id':draft['person_id'],'display_name':ADULTS[draft['person_id']],'created_at':stamp(),'enrollment_started_at':draft['created_at'],'status':'candidate_unqualified','recognition_enabled':False,'authorizes_personal_memory':False,'model_sha256':next(iter(hashes)),'dimension':next(iter(dimensions)),'centroid':centroid.tolist(),'clips':draft['clips'],'retain_audio':draft['retain_audio'],'consent':draft['consent'],'local_only':True,'consistency_cosines':(vectors@centroid).tolist(),'threshold':None,'unknown_speaker_qualified':False,'held_out_session_qualified':False,'workflow_run':draft.get('workflow_run'),'note':note})
   return self.state(token)
