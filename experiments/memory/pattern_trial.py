"""Fresh independent-session semantic diagnostic; no audio or raw-source fallback."""
import asyncio,json,os,time
from experiments.memory.runtime import ROOT,SSD,require_ssd
from experiments.memory.learning_gateway import LearningGateway
from experiments.memory.pilot import Process
from experiments.memory.context_envelope import pack
from experiments.memory.reply_boundary import qualify_context
from experiments.memory.native_text import NativeTextReference
from tavi.storage import Store
from tavi.experiment_workflow import begin,audit,digest

async def run():
 require_ssd();folder,plan=begin(ROOT/'experiments/memory/pattern-protocol-v1.json',run_root=SSD/'runs/scored');print(json.dumps({'run':str(folder),'audit':audit(folder)}),flush=True)
 (ROOT/'.tavi/pattern-active-run.txt').write_text(str(folder));fixture=json.loads((ROOT/'experiments/memory/pattern-input-v1.json').read_text())
 os.environ['TIKTOKEN_CACHE_DIR']=str(SSD/'models/tiktoken');import tiktoken
 encoding=tiktoken.get_encoding('o200k_base');logs=folder/'logs';logs.mkdir();directory=folder/('pattern-'+folder.name)
 ledger=Store(ROOT/'.tavi/simulation/simulation.sqlite3');initial=ledger.used_micro_usd();deadline=time.monotonic()+plan['limits']['maximum_wall_seconds'];worker=None;gateway=None;ref=None;sources=[]
 result={'ingests':[],'cases':[],'errors':[],'initial_spent_reserved_usd':initial/1e6,'native_directory':str(directory),'audio':False,'physical_playback':False}
 class Budget:
  calls=0
  def reserve(self,key,amount,cap):
   if self.calls>=8:raise ValueError('Reply request bound')
   ledger.reserve(key,amount,min(cap,initial+2_000_000));self.calls+=1
  def settle(self,key,amount):ledger.settle(key,amount)
 budget=Budget()
 def remaining():
  value=deadline-time.monotonic()
  if value<=0:raise TimeoutError('Pattern diagnostic overall deadline')
  return value
 def save():
  result.update(additional_api_usd=(ledger.used_micro_usd()-initial)/1e6,total_spent_reserved_usd=ledger.used_micro_usd()/1e6,reply_calls=budget.calls,sources=sources)
  (folder/'observations.json').write_text(json.dumps(result,indent=2)+'\n')
 def send(request):
  out=worker.send(request,timeout=min(420,remaining()))
  if not out['ok']:raise RuntimeError(out['error'])
  return out['result']
 def ingest(source):
  start=time.monotonic();native=send({'op':'ingest','episode':source,'people':fixture['people']});sources.append(source)
  result['ingests'].append({'source':source['id'],'elapsed_ms':(time.monotonic()-start)*1000,'native':native});save()
 async def query(case):
  nonlocal ref
  native=send({'op':'query','question':case,'people':fixture['people']})
  context=pack('hindsight',native['native_context'],sources,case['audience_ids'],encoding)
  task={'people':fixture['people'],'actual_speaker_id':case['asker'],'audience_ids':case['audience_ids'],'conversation_at':case['at'],'question':case['text'],'catalogue':[],'recent_conversation':[]}
  boundary=qualify_context(task,json.loads(context['context']),sources);row={'id':case['id'],'task':task,'native':native,'packed':context,'boundary':boundary};result['cases'].append(row)
  ref=NativeTextReference(budget)
  try:
   async with asyncio.timeout(min(60,remaining())):
    await ref.connect();row['reply']=await ref.reply(task,boundary['evidence'],case['id'])
  finally:await ref.close();ref=None
  save();print(json.dumps({'id':case['id'],'facts':len(boundary['evidence']['facts']),'reply':row['reply']['text']}),flush=True)
 try:
  gateway=LearningGateway(folder);await asyncio.to_thread(gateway.start)
  worker=Process('hindsight',directory,logs,'learning_worker.py');send({'op':'initialize'})
  for source in fixture['episodes'][:10]:ingest(source)
  for case in fixture['queries'][:6]:await query(case)
  for source in fixture['episodes'][10:]:ingest(source)
  for case in fixture['queries'][6:]:await query(case)
 except Exception as e:result['errors'].append(type(e).__name__+': '+str(e));print(json.dumps({'error_type':type(e).__name__}),flush=True)
 finally:
  if ref:await ref.close()
  if worker:worker.stop()
  if gateway:result['gateway_disabled']=await asyncio.to_thread(gateway.close)
  save();ledger.close()
 print(json.dumps({'awaiting_source_review':str(folder),'errors':result['errors'],'cost':result['additional_api_usd']}),flush=True)
if __name__=='__main__':asyncio.run(run())
