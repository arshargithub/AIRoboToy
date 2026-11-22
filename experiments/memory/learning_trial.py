"""Bounded fictional accepted-turn -> native extraction -> response qualification.
Run only against an already frozen protocol; no microphone or hand-entered facts.
"""
import asyncio,hashlib,json,os,sqlite3,sys,time,urllib.request
from pathlib import Path
from experiments.memory.runtime import ROOT,SSD,require_ssd
from experiments.memory.pilot import Process
from experiments.memory.learning_queue import LearningConversation,LearningQueue
from experiments.memory.context_envelope import pack
from experiments.memory.reply_boundary import qualify_context
from experiments.memory.native_text import NativeTextReference
from tavi.storage import Store
from tavi.conversation_providers import Speech
from tavi.experiment_workflow import audit,digest

async def run(folder):
 require_ssd();folder=Path(folder);print(json.dumps(audit(folder)),flush=True)
 record=json.loads((folder/'run.json').read_text());plan=json.loads((folder/'protocol.json').read_text())
 if record['state']!='running' or record['experiment_id']!='MEMORY-AUTO-LEARNING-01':raise ValueError('Wrong or finished run')
 for p,sha in record['source_sha256'].items():
  if digest(ROOT/p)!=sha:raise ValueError('Source changed before execution')
 for p,sha in record['input_sha256'].items():
  if digest(ROOT/p)!=sha:raise ValueError('Input changed before execution')
 manifest=json.loads((ROOT/'experiments/memory/learning-environment-v1.json').read_text())
 for f in manifest['files']:
  if digest(f['path'])!=f['sha256']:raise ValueError('Native/model asset changed')
 fixture=json.loads((ROOT/'experiments/memory/learning-input-v1.json').read_text());people=fixture['people']
 os.environ['TIKTOKEN_CACHE_DIR']=str(SSD/'models/tiktoken');import tiktoken
 encoding=tiktoken.get_encoding('o200k_base')
 directory=folder/('native-'+folder.name);logs=folder/'logs';logs.mkdir()
 ledger=Store(ROOT/'.tavi/simulation/simulation.sqlite3');initial=ledger.used_micro_usd()
 result={'events':[],'cases':[],'errors':[],'initial_spent_reserved_micro_usd':initial,'native_directory':str(directory),'physical_playback':False,'human_audio':False}
 deadline=time.monotonic()+plan['limits']['maximum_wall_seconds'];worker=None;queue=None;c=None;ref=None;scope={};source_ids={};number=0;restarts=0
 class Envelope:
  calls=0
  def reserve(self,key,amount,cap):
   if self.calls>=9:raise ValueError('Reply call bound')
   # Combined ledger may grow through broker calls. This stricter reply ceiling
   # plus broker's independent $1 ceiling preserves the total additional $3.
   ledger.reserve(key,amount,min(cap,initial+2_000_000));self.calls+=1
  def settle(self,key,amount):ledger.settle(key,amount)
 envelope=Envelope()
 class NoPaidReply:
  async def stream_reply(self,history):yield 'Thank you for telling me.'
  async def close(self):pass
 class NoPlayback:
  async def synthesize(self,text):return Speech(b'not-played',100)
 def remaining():
  value=deadline-time.monotonic()
  if value<=0:raise TimeoutError('Overall learning run deadline')
  return value
 def save():
  result.update(additional_api_usd=(ledger.used_micro_usd()-initial)/1e6,total_spent_reserved_usd=ledger.used_micro_usd()/1e6,source_ids=source_ids,restarts=restarts,reply_calls=envelope.calls)
  (folder/'observations.json').write_text(json.dumps(result,indent=2)+'\n')
 def send(value):
  answer=worker.send(value,timeout=min(420,remaining()))
  if not answer['ok']:raise ValueError(answer['error'])
  return answer['result']
 def open_worker():
  nonlocal worker
  worker=Process('hindsight',directory,logs,'learning_worker.py');send({'op':'initialize'})
 async def open_queue():
  nonlocal queue,c
  queue=LearningQueue(folder/'learning.sqlite3')
  c=LearningConversation(ledger,provider=NoPaidReply(),speech=NoPlayback(),context_revision=lambda:scope,learning_queue=queue)
  result['sqlite']={'journal_mode':queue.db.execute('PRAGMA journal_mode').fetchone()[0],'synchronous':queue.db.execute('PRAGMA synchronous').fetchone()[0]}
 async def restart():
  nonlocal restarts
  before=queue.sources();await c.close();queue.close();worker.stop();open_worker();await open_queue()
  after=queue.sources();same=before==after;restarts+=1;result.setdefault('restart_checks',[]).append(same);save()
  if not same:raise ValueError('Queue changed after restart')
 async def capture(item):
  nonlocal number
  remaining();number+=1;c.stop();scope.clear();scope.update(session_id='fiction-'+item['alias'],revision=number,task={'actual_speaker_id':item['speaker'],'people':people,'audience_ids':item['audience'],'conversation_at':item['at']})
  c.start('fiction');c.feed('fiction',{'events':[{'type':'speech_started','utterance':number},{'type':'recognition','utterance':number,'text':item['text'],'final':True,'recognition_id':item['alias']}]})
  if not c.learning_events:raise ValueError('Controller did not call accepted-turn hook')
  event=c.learning_events[-1];result['events'].append({'type':'capture','alias':item['alias'],**event})
  if event.get('queued'):source_ids[item['alias']]=event['source_id']
  await asyncio.sleep(0)
  return event
 def ingest(job):
  start=time.monotonic();native=send({'op':'ingest','episode':job['source'],'people':people})
  result['events'].append({'type':'ingest','source':job['source'],'result':native,'elapsed_ms':(time.monotonic()-start)*1000});save();return native
 async def flush():
  while (job:=queue.claim()) is not None:
   ingest(job)
   if not queue.complete(job):raise ValueError('Job revoked or stale after dispatch')
   save()
 async def query(item):
  remaining();native=send({'op':'query','question':{'id':item['id'],'asker':item['speaker'],'audience_ids':item['audience'],'text':item['text'],'at':item['at']},'people':people})
  row={'id':item['id'],'question':item,'native':native};result['cases'].append(row)
  if native.get('blocked'):
   row['reply_skipped']=True;save();return
  sources=queue.sources();packed=pack('hindsight',native['native_context'],sources,item['audience'],encoding)
  task={'actual_speaker_id':item['speaker'],'people':people,'audience_ids':item['audience'],'conversation_at':item['at'],'question':item['text'],'recent_conversation':[],'catalogue':[]}
  boundary=qualify_context(task,json.loads(packed['context']),sources);row.update(packed=packed,boundary=boundary)
  nonlocal ref
  ref=NativeTextReference(envelope)
  try:
   async with asyncio.timeout(min(60,remaining())):
    await ref.connect();row['reply']=await ref.reply(task,boundary['evidence'],item['id'])
  finally:
   await ref.close();ref=None
  save();print(json.dumps({'id':item['id'],'facts':len(boundary['evidence']['facts']),'reply':row['reply']['text']}),flush=True)
 try:
  open_worker();await open_queue()
  # Crash-window control: native completes, application ACK is deliberately
  # omitted. Stop old owner, reopen both ledgers, recover that exact job only.
  first=fixture['episodes'][0];await capture(first);job=queue.claim();ingest(job)
  await restart();assert queue.recover_stopped_job(job);new=queue.claim();before=ledger.used_micro_usd();native=ingest(new)
  result['duplicate_after_stopped_job_no_inference']=bool(native.get('duplicate')) and before==ledger.used_micro_usd() and not queue.complete(job) and queue.complete(new)
  for item in fixture['episodes'][1:4]:await capture(item);await flush()
  await restart()
  for item in fixture['queries'][:4]:await query(item)
  for item in fixture['episodes'][4:]:
   event=await capture(item)
   if item['alias']=='unknown':result['unknown_write_blocked']=not event.get('queued') and event.get('reason')=='unknown_speaker'
   await flush()
  result['known_sources_completed']=len(queue.sources());await restart()
  for item in fixture['queries'][4:9]:await query(item)
  result['unknown_query_blocked']=next(r for r in result['cases'] if r['id']=='unknown').get('reply_skipped',False)
  sid=source_ids['private'];result['revoked_locally']=queue.revoke(sid)
  result['native_delete']=send({'op':'delete','source_id':sid});await restart();await query(fixture['queries'][-1])
  result['revocation_canonical_excluded']=sid not in {s['id'] for s in queue.sources()}
  result['restart_durable']=len(result['restart_checks'])>=3 and all(result['restart_checks'])
  result['final_sources']=queue.sources();result['pending']=queue.pending()
 except Exception as e:
  result['errors'].append(type(e).__name__+': '+str(e));print(json.dumps({'error_type':type(e).__name__}),flush=True)
 finally:
  if ref:await ref.close()
  if c:await c.close()
  if queue:queue.close()
  if worker:worker.stop()
  try:
   config=json.loads((SSD/'private-config/broker.json').read_text());request=urllib.request.Request(config['base_url']+'/control/disable-paid',data=b'{}',headers={'Authorization':'Bearer '+config['token'],'Content-Type':'application/json'})
   with urllib.request.urlopen(request,timeout=15) as response:result['broker_disable']=json.load(response)
  except Exception as e:result['errors'].append('Disable paid gateway: '+type(e).__name__)
  save();ledger.close()
 print(json.dumps({'run':str(folder),'errors':result['errors'],'additional_api_usd':result['additional_api_usd']}),flush=True)

if __name__=='__main__':asyncio.run(run(sys.argv[1]))
