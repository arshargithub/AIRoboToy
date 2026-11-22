"""Consent-triggered bounded loopback gateway; never changes upstream destination."""
import fcntl,json,os,signal,subprocess,time,urllib.request
from experiments.memory.runtime import ROOT,SSD,engine_environment
class LearningGateway:
 def __init__(self,folder,*,project_ceiling_micro_usd=None,maximum_calls=64):
  from tavi.storage import APPROVED_BUDGET_MICRO_USD
  if project_ceiling_micro_usd is not None and (type(project_ceiling_micro_usd) is not int or not 0<=project_ceiling_micro_usd<=APPROVED_BUDGET_MICRO_USD):raise ValueError('Invalid project ceiling')
  if type(maximum_calls) is not int or not 0<=maximum_calls<=64:raise ValueError('Invalid learning call limit')
  self.folder=folder;self.lock=None;self.locked=False;self.process=None;self.ready=False;self.project_ceiling_micro_usd=project_ceiling_micro_usd;self.maximum_calls=maximum_calls
 def health(self):
  with urllib.request.urlopen('http://127.0.0.1:8790/health',timeout=3) as r:return json.load(r)
 def start(self):
  self.lock=open(SSD/'private-config/learning-gateway.owner','a')
  try:
   fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
   self.locked=True
   old=json.loads((SSD/'private-config/broker.json').read_text())
   if old['base_url']!='http://127.0.0.1:8790' or self.health()['paid_enabled']:raise ValueError('Another memory test is active. Stop it before starting this one.')
   command=subprocess.check_output(['/bin/ps','-p',str(old['pid']),'-o','command='],text=True)
   if not any(x in command for x in ['experiments.memory.learning_broker','experiments/memory/runtime.py broker ']):raise ValueError('Local gateway process cannot be verified')
   os.kill(old['pid'],signal.SIGTERM)
   deadline=time.monotonic()+3
   while True:
    try:self.health()
    except Exception:break
    if time.monotonic()>deadline:raise TimeoutError('Old gateway still listening')
    time.sleep(.05)
   with open(self.folder/'gateway-launch.log','a') as log:
    args=[str(SSD/'venvs/broker/bin/python'),'-m','experiments.memory.learning_broker',str(self.folder/'gateway')]
    args+=['--maximum-calls',str(self.maximum_calls)]
    if self.project_ceiling_micro_usd is not None:args+=['--project-ceiling-micro-usd',str(self.project_ceiling_micro_usd)]
    p=subprocess.Popen(args,cwd=ROOT,env=engine_environment(),stdout=log,stderr=log,start_new_session=True)
   self.process=p
   deadline=time.monotonic()+15
   while True:
    if p.poll() is not None:raise RuntimeError('Local memory gateway did not start')
    try:
     value=self.health()
    except Exception:value=None
    if value and value['paid_enabled']:
     self.ready=True
     if (value.get('project_ceiling_micro_usd')!=self.project_ceiling_micro_usd
         or value.get('maximum_usd')!=1 or value.get('maximum_calls')!=self.maximum_calls):raise ValueError('Gateway spending receipt mismatch')
     return value
    if time.monotonic()>deadline:raise TimeoutError('Local memory gateway startup timed out')
    time.sleep(.1)
  except BaseException:
   if self.process and not self.ready:
    self.process.terminate();self.process.wait(timeout=5)
   self.close();raise
 def _unlock(self):
  if self.locked:fcntl.flock(self.lock,fcntl.LOCK_UN)
  if self.lock:self.lock.close()
  self.lock=None;self.locked=False
 def close(self):
  if not self.lock:return
  if not self.locked or not self.ready:
   self._unlock();return
  old=json.loads((SSD/'private-config/broker.json').read_text())
  if old['pid']!=self.process.pid or old['directory']!=str(self.folder/'gateway'):
   raise ValueError('Gateway ownership changed; refusing to disable another run')
  req=urllib.request.Request(old['base_url']+'/control/disable-paid',data=b'{}',headers={'Authorization':'Bearer '+old['token']})
  # Keep ownership on error: a later close must be able to retry shutdown.
  with urllib.request.urlopen(req,timeout=10) as r:result=json.load(r)
  self.ready=False;self._unlock();return result
