"""Opt-in fictional adult pilot: existing controller/ASR/browser, no memory writes."""
import asyncio
from copy import deepcopy
import hashlib
import json
import os
import sqlite3
import threading
from pathlib import Path
from uuid import uuid4
from experiments.memory.runtime import ROOT,SSD,require_ssd
from experiments.memory.pilot import Process
from experiments.memory.context_envelope import pack
from experiments.memory.conversation_adapter import make_conversation
from tavi.experiment_workflow import begin,audit

CONSENT='adult-fictional-local-asr-cloud-text-v1'

class PilotBudget:
    def __init__(self,store):
        self.store=store;self.initial=store.used_micro_usd();self.calls=0
    def reserve(self,key,amount,cap):
        if self.calls>=8:raise ValueError('Pilot request limit reached. Mute and save this attempt.')
        self.store.reserve(key,amount,min(cap,self.initial+2_000_000));self.calls+=1
    def settle(self,key,amount):self.store.settle(key,amount)

class AdultMemoryPilot:
    def __init__(self,store):
        require_ssd();self.store=store;self.budget=PilotBudget(store)
        self.folder=None;self.worker=None;self.lock=threading.Lock();self.rows=[];self.last_saved=None;self.last_key=None
        fixture=json.loads((ROOT/'experiments/memory/decision-v2-input.json').read_text())
        self.sources=[s for s in fixture['episodes'] if s['speaker_id']!='unknown']
        self.directory=Path(json.loads((ROOT/'experiments/memory/voice-integration-input.json').read_text())['native_directory'])
        revision=hashlib.sha256(json.dumps(self.sources,sort_keys=True).encode()).hexdigest()
        cases=json.loads((ROOT/'experiments/memory/combined-input-v1.json').read_text())['cases']
        catalogue=next(c['catalogue'] for c in cases if c['id']=='book1')+next(c['catalogue'] for c in cases if c['id']=='gift1')
        self.scope={'revision':revision,'task':{'people':fixture['people'],'actual_speaker_id':'a','audience_ids':['a','b','c','d'],'conversation_at':'2026-09-20T12:00:00Z','catalogue':catalogue}}
        self.encoding=None
    def conversation(self,store,*,speech):
        return make_conversation(store,scope=lambda:deepcopy(self.scope),recall=self.recall,speech=speech,provider_store=self.budget)
    async def prepare(self,body):
        if body.get('pilot_consent')!=CONSENT or body.get('adult') is not True or body.get('online') is not True or type(body.get('record_audio')) is not bool:
            raise ValueError('Choose adult-only fictional testing and local speech processing with online text replies before starting.')
        if self.worker:return
        # Freeze before querying the bank or sending any inference request.
        if self.folder is None:
            self.folder,_=begin(ROOT/'experiments/memory/adult-pilot-protocol-v1.json',run_root=SSD/'runs/scored',consent={'adult':True,'recording':True,'cloud':False,'retain_audio':body['record_audio'],'cloud_text':True,'fictional_role':'Nora'})
            audit(self.folder)
        db=sqlite3.connect(f'file:{self.directory}/source-ledger.sqlite3?mode=ro',uri=True)
        try:actual=[json.loads(r[0]) for r in db.execute('SELECT body FROM episodes WHERE complete=1 AND deleted=0')]
        finally:db.close()
        if sorted(actual,key=lambda s:s['id'])!=sorted(self.sources,key=lambda s:s['id']):raise ValueError('Fictional memory generation changed; save and stop for inspection.')
        import tiktoken
        os.environ['TIKTOKEN_CACHE_DIR']=str(SSD/'models/tiktoken');self.encoding=tiktoken.get_encoding('o200k_base')
        logs=self.folder/'logs';logs.mkdir(exist_ok=True)
        self.worker=Process('hindsight',self.directory,logs,'guarded_worker.py')
        try:await asyncio.to_thread(self.send,{'op':'initialize'})
        except BaseException:
            self.worker.stop();self.worker=None;raise
    def send(self,request):
        # A cancelled asyncio caller cannot interleave the stdio protocol with
        # a subsequent query still finishing in another worker thread.
        with self.lock:
            value=self.worker.send(request,timeout=45)
        if not value['ok']:raise ValueError(value['error'])
        return value['result']
    async def recall(self,task):
        if not self.worker:raise ValueError('Start the consented memory pilot first.')
        query={'id':uuid4().hex,'asker':task['actual_speaker_id'],'audience_ids':task['audience_ids'],'text':task['question'],'at':task['conversation_at']}
        native=await asyncio.to_thread(self.send,{'op':'query','question':query,'people':task['people']})
        packed=pack('hindsight',native['native_context'],self.sources,task['audience_ids'],self.encoding)
        self.rows.append({'question_id':query['id'],'query':query,'native':native,'packed':packed})
        return {'evidence':json.loads(packed['context']),'sources':self.sources}
    def persist(self,conversation):
        if not self.folder:return
        # Write only on completed/failed provider observations, not each PCM ACK.
        rows=list(conversation.provider.observations)
        ready=[r for r in rows if r.get('completed') or r.get('error_type')]
        key=(tuple((r['id'],r.get('completed'),r.get('error_type')) for r in ready),self.budget.calls,len(self.rows))
        if key==self.last_key:return
        self.last_key=key
        value={'scope':self.scope,'provider_observations':ready,'native_rows':self.rows,'api_calls':self.budget.calls,'additional_api_usd':(self.store.used_micro_usd()-self.budget.initial)/1e6,'audio_upload':False,'memory_writes':False}
        raw=json.dumps(value,indent=2);sha=hashlib.sha256(raw.encode()).hexdigest()
        if sha==self.last_saved:return
        tmp=self.folder/'observations.pending';tmp.write_text(raw+'\n');tmp.replace(self.folder/'observations.json');self.last_saved=sha
    async def close(self,conversation):
        self.persist(conversation)
        if self.worker:
            worker=self.worker
            def stop():
                with self.lock:worker.stop()
            await asyncio.to_thread(stop);self.worker=None
