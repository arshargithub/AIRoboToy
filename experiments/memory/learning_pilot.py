"""Explicitly consented adult fictional learn/restart/correct pilot, opt-in only."""
import asyncio,json,os,time
from datetime import datetime,timezone
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
from experiments.memory.adult_pilot import AdultMemoryPilot,PilotBudget
from experiments.memory.runtime import ROOT,SSD,require_ssd
from experiments.memory.learning_gateway import LearningGateway
from experiments.memory.learning_queue import LearningQueue,LearningConversation
from experiments.memory.learning_supervisor import LearningSupervisor,NativeLearningClient
from experiments.memory.conversation_adapter import MemoryTextProvider
from experiments.memory.native_text import NativeTextReference
from tavi.experiment_workflow import begin,audit

CONSENT='adult-fictional-learning-local-speech-cloud-text-v1'
class LearningPilot(AdultMemoryPilot):
 def __init__(self,store):
  require_ssd();self.store=store;self.budget=PilotBudget(store)
  self.folder=None;self.worker=None;self.rows=[];self.last_key=None;self.last_saved=None
  self.lock=__import__('threading').Lock();self.encoding=None;self.queue=None;self.supervisor=None;self.gateway=None;self.closed=False;self.checkpoints=[]
  self.scope={'session_id':uuid4().hex,'task':{'people':{'a':'Mira','b':'Leon','c':'June','d':'Oscar'},'actual_speaker_id':'a','audience_ids':['a','b','c','d'],'conversation_at':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),'catalogue':[]}}
  self.deadline=None;self.watchdog=None;self.stop_task=None
  self.end_lock=asyncio.Lock()
  self.checkpoint_task=None
  self.gateway_task=None
 def current_scope(self):
  return {**deepcopy(self.scope),'memory_epoch':self.queue.generation() if self.queue else 0}
 def capture(self,*args):
  if not self.queue or self.closed:return {'queued':False,'reason':'learning_not_active'}
  return self.queue.capture(*args)
 def notify(self):
  if self.supervisor:self.supervisor.notify()
 def conversation(self,store,*,speech):
  provider=MemoryTextProvider(self.budget,scope=self.current_scope,recall=self.recall,reference_factory=NativeTextReference)
  def prepare_turn():self.scope['task']['conversation_at']=datetime.now(timezone.utc).isoformat()
  return LearningConversation(store,provider=provider,speech=speech,context_revision=self.current_scope,sentence_minimum=1,learning_queue=self,learning_notify=self.notify,learning_prepare=prepare_turn)
 async def prepare(self,body):
  if body.get('pilot_consent')!=CONSENT or body.get('adult') is not True or body.get('online') is not True or type(body.get('record_audio')) is not bool:
   raise ValueError('Choose adult fictional learning and local speech with online text before starting.')
  if self.closed:raise ValueError('This attempt has ended. Save its results; a new isolated attempt needs a fresh service session.')
  if self.worker:return
  self.folder,_=begin(ROOT/'experiments/memory/learning-adult-protocol-v1.json',run_root=SSD/'runs/scored',consent={'adult':True,'recording':True,'cloud':False,'cloud_text':True,'retain_audio':body['record_audio'],'fictional_role':'Mira','automatic_memory_writes':True})
  audit(self.folder);self.directory=self.folder/('learning-'+self.folder.name);(self.folder/'logs').mkdir()
  try:
   self.gateway=LearningGateway(self.folder);self.gateway_task=asyncio.create_task(asyncio.to_thread(self.gateway.start));await asyncio.shield(self.gateway_task)
   import tiktoken
   os.environ['TIKTOKEN_CACHE_DIR']=str(SSD/'models/tiktoken');self.encoding=tiktoken.get_encoding('o200k_base')
   self.queue=LearningQueue(self.folder/'learning.sqlite3');self._start_supervisor()
   from experiments.memory.pilot import Process
   self.worker=Process('hindsight',self.directory,self.folder/'logs','learning_worker.py');await asyncio.to_thread(self.send,{'op':'initialize'})
   self.deadline=time.monotonic()+600
   async def expire():
    await asyncio.sleep(600);await self.end_learning()
   self.watchdog=asyncio.create_task(expire())
  except BaseException:
   await self.end_learning();raise
 def _start_supervisor(self):
  self.supervisor=LearningSupervisor(self.queue.path,lambda:NativeLearningClient(self.directory,self.folder/'logs',self.scope['task']['people']),maximum_jobs=8);self.supervisor.start()
 @property
 def sources(self):return self.queue.sources() if self.queue else []
 def extra_state(self,conversation):
  events=list(conversation.learning_events)
  status=self.supervisor.snapshot() if self.supervisor else {'status':'not_started'}
  return {'learning':{'status':status['status'],'pending':self.queue.pending() if self.queue else 0,'completed':len(self.sources),'error':next((e['reason'] for e in reversed(events) if e.get('reason')),None),'checkpoints':list(self.checkpoints),'closed':self.closed}}
 async def checkpoint(self,conversation,stage):
  if self.checkpoint_task and not self.checkpoint_task.done():return await asyncio.shield(self.checkpoint_task)
  self.checkpoint_task=asyncio.create_task(self._checkpoint(conversation,stage))
  return await asyncio.shield(self.checkpoint_task)
 async def _checkpoint(self,conversation,stage):
  if stage not in (1,2):raise ValueError('Unknown learning checkpoint')
  if stage in self.checkpoints:return {'ready':True,'checkpoint':stage}
  if self.closed or not self.queue:raise ValueError('Learning attempt is not active')
  if stage!=len(self.checkpoints)+1:raise ValueError('Finish the earlier memory check first')
  state=self.extra_state(conversation)['learning']
  if state['error'] or state['status'] in ['needs_reconciliation','owner_busy','job_bound']:raise ValueError('A memory could not be saved. Stop and save this partial attempt.')
  if state['pending']:return {'ready':False}
  if conversation.audio or (conversation.task and not conversation.task.done()):return {'ready':False}
  conversation.command(conversation.lease,'end',{})
  before=self.sources
  await asyncio.to_thread(self.supervisor.stop,abort=False)
  worker=self.worker
  await asyncio.to_thread(worker.stop)
  if self.closed:return {'ready':False}
  # Reopen both canonical queue and native query worker. No prior chat history
  # can answer the next request; the next phrase includes the wake name.
  old=self.queue;self.queue=LearningQueue(old.path);old.close()
  from experiments.memory.pilot import Process
  self.worker=Process('hindsight',self.directory,self.folder/'logs','learning_worker.py');await asyncio.to_thread(self.send,{'op':'initialize'})
  if self.sources!=before or conversation.history:raise ValueError('Restart did not preserve only canonical memories')
  self._start_supervisor();self.checkpoints.append(stage);return {'ready':True,'checkpoint':stage}
 def persist(self,conversation):
  if not self.folder:return
  state=self.extra_state(conversation);ready=[r for r in conversation.provider.observations if r.get('completed') or r.get('error_type')]
  key=(tuple((r['id'],r.get('completed'),r.get('error_type')) for r in ready),len(self.rows),len(self.sources),state['learning']['pending'],state['learning']['status'],self.closed,len(self.checkpoints))
  if key==self.last_key:return
  self.last_key=key
  value={'scope':self.current_scope(),'provider_observations':ready,'native_rows':self.rows,'learning_events':list(conversation.learning_events),'supervisor':self.supervisor.snapshot() if self.supervisor else None,'sources':self.sources,'checkpoints':self.checkpoints,'api_calls':self.budget.calls,'additional_api_usd':(self.store.used_micro_usd()-self.budget.initial)/1e6,'memory_writes':True,'audio_upload':False}
  value['durable_learning_diagnostics']=self.queue.diagnostics() if self.queue else None
  tmp=self.folder/'observations.pending';tmp.write_text(json.dumps(value,indent=2)+'\n');tmp.replace(self.folder/'observations.json')
 async def end_learning(self):
  async with self.end_lock:
   self.closed=True
   try:
    if self.gateway_task:await asyncio.gather(self.gateway_task,return_exceptions=True)
    if self.checkpoint_task:await asyncio.gather(self.checkpoint_task,return_exceptions=True)
    if self.supervisor:await asyncio.to_thread(self.supervisor.stop)
   finally:
    if self.gateway:await asyncio.to_thread(self.gateway.close)
 async def close(self,conversation):
  if self.watchdog:self.watchdog.cancel()
  if self.stop_task:await asyncio.gather(self.stop_task,return_exceptions=True)
  await self.end_learning();await super().close(conversation)
  if self.queue:self.queue.close();self.queue=None
