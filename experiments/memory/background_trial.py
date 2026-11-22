"""Zero-paid local scheduling/durability probe, not real inference latency."""
import asyncio,json,math,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from experiments.memory.learning_queue import LearningQueue,LearningConversation
from experiments.memory.learning_supervisor import LearningSupervisor
from experiments.memory.runtime import ROOT,SSD,require_ssd
from tavi.storage import Store
from tavi.conversation_providers import Speech
from tavi.experiment_workflow import begin,audit,finish

async def run():
 require_ssd();folder,plan=begin(ROOT/'experiments/memory/background-protocol-v1.json',run_root=SSD/'runs/scored');print(json.dumps(audit(folder)),flush=True)
 cfg=json.loads((ROOT/'experiments/memory/background-input-v1.json').read_text());ledger=Store(ROOT/'.tavi/simulation/simulation.sqlite3');initial=ledger.used_micro_usd()
 q=LearningQueue(folder/'queue.sqlite3');scope={'session_id':'background-fixture','task':{'actual_speaker_id':'a','people':{'a':'Mira'},'audience_ids':['a'],'conversation_at':'2026-10-01T12:00:00Z'}}
 gate=threading.Event();entered=threading.Event()
 class Client:
  def initialize(self):pass
  def ingest(self,source):
   entered.set()
   if not gate.wait(5):raise TimeoutError('Controlled gate')
   time.sleep(.002);return {'simulation':True}
  def abort(self):gate.set()
  def close(self):pass
 class Provider:
  async def stream_reply(self,history):yield 'That sounds fun.'
  async def close(self):pass
 class Voice:
  async def synthesize(self,text):return Speech(b'no-playback',100)
 s=LearningSupervisor(q.path,Client,maximum_jobs=cfg['sources']);s.start()
 c=LearningConversation(ledger,provider=Provider(),speech=Voice(),context_revision=lambda:scope,learning_queue=q,learning_notify=s.notify);c.start('synthetic')
 result={'errors':[],'capture_ms':[],'heartbeat_delay_ms':[],'native_inference':False,'audio':False,'worker':'controlled delayed local client; not Hindsight'};done=False
 async def beat():
  while not done:
   t=time.monotonic();await asyncio.sleep(.005);result['heartbeat_delay_ms'].append(max(0,(time.monotonic()-t-.005)*1000))
 async def wait(fn):
  async with asyncio.timeout(min(5,max(0,deadline-time.monotonic()))):
   while not fn():await asyncio.sleep(.002)
 task=asyncio.create_task(beat());start=time.monotonic();deadline=start+plan['limits']['maximum_wall_seconds']
 try:
  c.feed('synthetic',{'events':[{'type':'speech_started','utterance':1},{'type':'recognition','utterance':1,'text':cfg['text'],'recognition_id':'initial','final':True}]})
  await wait(lambda:c.audio is not None and entered.is_set());result['reply_ready_while_save_blocked_ms']=(time.monotonic()-start)*1000
  result['reply_ready_while_save_blocked']=not gate.is_set() and not q.sources();gate.set()
  for n in range(1,cfg['sources']):
   await wait(lambda:q.pending()<8)
   t=time.monotonic();event=q.capture(scope,SimpleNamespace(response_id='unused-'+str(n)),cfg['text'],'recognition-'+str(n));result['capture_ms'].append((time.monotonic()-t)*1000)
   if not event['queued']:raise ValueError('Unexpected rejected source')
   s.notify();await asyncio.sleep(.002)
  await wait(lambda:q.pending()==0);result['completed_sources']=len(q.sources());result['supervisor']=s.snapshot()
 except Exception as e:result['errors'].append(type(e).__name__+': '+str(e))
 finally:
  gate.set();await c.close();await asyncio.to_thread(s.stop);q.close();done=True;await task
 stream=__import__('io').StringIO();suite=unittest.defaultTestLoader.loadTestsFromName('tests.test_learning_supervisor')
 tests=await asyncio.to_thread(unittest.TextTestRunner(stream=stream).run,suite);result['invariants']={'count':tests.testsRun,'failures':len(tests.failures),'errors':len(tests.errors)}
 def p95(values):return sorted(values)[math.ceil(.95*len(values))-1] if values else None
 metrics={'completed_sources':result.get('completed_sources'),'reply_ready_while_save_blocked':result.get('reply_ready_while_save_blocked'),'reply_ready_while_save_blocked_ms':result.get('reply_ready_while_save_blocked_ms'),'capture_p95_ms':p95(result['capture_ms']),'capture_max_ms':max(result['capture_ms'],default=None),'heartbeat_p95_delay_ms':p95(result['heartbeat_delay_ms']),'heartbeat_max_delay_ms':max(result['heartbeat_delay_ms'],default=None),'invariant_checks_passed':tests.testsRun-len(tests.failures)-len(tests.errors),'collection_errors':len(result['errors']),'additional_api_usd':(ledger.used_micro_usd()-initial)/1e6}
 ledger.close();result['metrics']=metrics;(folder/'observations.json').write_text(json.dumps(result,indent=2)+'\n')
 sealed=finish(folder,metrics,artifacts=[folder/'observations.json',folder/'queue.sqlite3'],completed=not result['errors'],error='; '.join(result['errors']) or None)
 report={'run':str(folder),'metrics':metrics,'decision':sealed['decision'],'audit':audit(folder),'critical_review':['Controlled local client and fake voice/reply measure scheduling only. They do not prove Hindsight consolidation or K/ASR latency under contention.','127 captures and128 total sources on the mounted SSD in one warm run; timings include WAL/FULL persistence and local claim/complete contention. Not disk-removal or sustained-household endurance.','Two-owner exclusion uses an OS advisory lock. Orphaned working jobs remain blocked for reconciliation; killing a client is not proof a remote extraction did not finish.','Stable recognition identity deduplicates redelivery within the same canonical session. Distinct new recognitions are new sources, not independent evidence of a lasting pattern.','New-source completion does not cancel replies; revocation epoch does. Tests prove queued output and history invalidated and late learning completion rejected; physical derivative erasure is not claimed.','Bounded backlog/storage failures preserve conversation reply and expose a failed learning event. Live UI must explain any unsaved memory and stop the scored learning flow.']}
 (ROOT/'docs/evaluations/paprika_memory_background_01.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
if __name__=='__main__':asyncio.run(run())
