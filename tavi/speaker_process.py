"""Bounded stdio owner for offline speaker embedding; kills timed-out native work."""
import base64,json,os,selectors,subprocess,sys,threading,time
from uuid import uuid4
from tavi.speaker_profile import ROOT
class SpeakerProcess:
 def __init__(self):self.process=None;self.buffer=b'';self.lock=threading.Lock()
 def _read(self,seconds):
  end=time.monotonic()+seconds
  with selectors.DefaultSelector() as select:
   select.register(self.process.stdout,selectors.EVENT_READ)
   while time.monotonic()<end:
    if b'\n' in self.buffer:
     line,self.buffer=self.buffer.split(b'\n',1);return json.loads(line)
    if self.process.poll() is not None:raise ValueError('Local voice worker stopped. Keep this recording and try again.')
    if not select.select(min(1,end-time.monotonic())):continue
    part=os.read(self.process.stdout.fileno(),65536)
    if not part:raise ValueError('Local voice worker ended. Keep this recording and try again.')
    self.buffer+=part
    if len(self.buffer)>100000:raise ValueError('Local voice result was too large. Keep this recording and try again.')
  raise TimeoutError('Local voice check took too long. Keep this recording and try again.')
 def _drop(self):
  if self.process:
   if self.process.poll() is None:self.process.kill()
   self.process.wait(timeout=5);self.process.stdin.close();self.process.stdout.close();self.process=None;self.buffer=b''
 def prepare(self):
  if self.process and self.process.poll() is None:return
  self._drop()
  self.process=subprocess.Popen([sys.executable,'-m','tavi.speaker_worker'],cwd=ROOT,env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'LANG':'en_US.UTF-8','PYTHONPATH':str(ROOT),'HF_HUB_OFFLINE':'1'},stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=0)
  if self._read(10)!={'ready':True,'protocol':1}:raise ValueError('The local voice model could not start. Reconnect the drive and try again.')
 def encode(self,pcm):
  with self.lock:
   try:
    self.prepare();rid=uuid4().hex
    raw=(json.dumps({'id':rid,'pcm':base64.b64encode(pcm).decode()})+'\n').encode()
    if len(raw)>400000:raise ValueError('Recording too large')
    self.process.stdin.write(raw);self.process.stdin.flush();out=self._read(20)
    if out.get('id')!=rid:raise ValueError('Local voice result was not bound to this recording.')
    if not out.get('ok'):raise ValueError(out.get('error','Record this phrase again.'))
    return out['result']
   except BaseException:self._drop();raise
 def close(self):
  with self.lock:self._drop()
 def cancel(self):
  # Non-blocking lease revocation; the owned reader reaps/cleans its child.
  process=self.process
  if process and process.poll() is None:
   try:process.kill()
   except ProcessLookupError:pass
