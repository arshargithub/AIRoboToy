"""Synthetic segmented speech -> local turbo -> fresh memory -> native text -> K.

No microphone, ambient audio, raw-audio upload or audible playback. Timing starts
at completed-clip submission, excludes endpointing/browser; accelerated playback
receipts test history ordering, not acoustic interruption or full E3 acceptance.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import wave
from dataclasses import asdict
from experiments.memory.runtime import ROOT,SSD,require_ssd
from experiments.memory.pilot import Process
from experiments.memory.context_envelope import pack
from experiments.memory.conversation_adapter import make_conversation
from experiments.memory.network_window import probe,clock,qualified
from tavi.local_speech import LocalSpeech,validate_wave
from tavi.mlx_final_asr import MlxFinalASR
from tavi.inference_schedule import ScheduledSpeech
from tavi.storage import Store
from tavi.experiment_workflow import begin,audit

async def run():
 import tiktoken
 require_ssd();os.environ['TIKTOKEN_CACHE_DIR']=str(SSD/'models/tiktoken')
 folder,plan=begin(ROOT/'experiments/memory/combined-protocol-v1.json',run_root=SSD/'runs/scored')
 print(json.dumps({'run':str(folder),'audit':audit(folder)}),flush=True)
 cases=json.loads((ROOT/'experiments/memory/combined-input-v1.json').read_text())['cases']
 fixture=json.loads((ROOT/'experiments/memory/decision-v2-input.json').read_text())
 settings=json.loads((ROOT/'experiments/memory/voice-integration-input.json').read_text())
 directory=Path(settings['native_directory']);db=sqlite3.connect(f'file:{directory}/source-ledger.sqlite3?mode=ro',uri=True)
 sources=[json.loads(x[0]) for x in db.execute('SELECT body FROM episodes WHERE complete=1 AND deleted=0')];db.close()
 if sorted(sources,key=lambda x:x['id'])!=sorted([s for s in fixture['episodes'] if s['speaker_id']!='unknown'],key=lambda x:x['id']):raise ValueError('Source generation changed')
 revision=hashlib.sha256(json.dumps(sources,sort_keys=True).encode()).hexdigest()
 logs=folder/'logs';logs.mkdir();audio_dir=folder/'audio';audio_dir.mkdir();worker=None
 ledger=Store(ROOT/'.tavi/simulation/simulation.sqlite3');initial=ledger.used_micro_usd()
 class Envelope:
  calls=0
  def reserve(self,key,amount,cap):
   if self.calls>=8 or ledger.used_micro_usd()+amount>initial+2_000_000:raise ValueError('Combined trial bound')
   ledger.reserve(key,amount,cap);self.calls+=1
  def settle(self,key,amount):ledger.settle(key,amount)
 envelope=Envelope();scope={};active={};native_rows=[];encoding=tiktoken.get_encoding('o200k_base')
 def send(request):
  value=worker.send(request,timeout=60)
  if not value['ok']:raise ValueError(value['error'])
  return value['result']
 async def recall(task):
  query={'id':active['id'],'asker':task['actual_speaker_id'],'audience_ids':task['audience_ids'],'text':task['question'],'at':task['conversation_at'],'catalogue':task['catalogue']}
  native=await asyncio.to_thread(send,{'op':'query','question':query,'people':task['people']})
  packed=pack('hindsight',native['native_context'],sources,task['audience_ids'],encoding)
  native_rows.append({'case_id':active['id'],'native':native,'packed':packed})
  return {'evidence':json.loads(packed['context']),'sources':sources}
 voice=ScheduledSpeech(LocalSpeech('kokoro-k-mlx'),asyncio.get_running_loop())
 asr=MlxFinalASR(voice,profile_stages=True)
 c=make_conversation(ledger,scope=lambda:scope,recall=recall,speech=voice,provider_store=envelope)
 result={'cases':[],'errors':[],'load_samples':[],'source_generation_sha256':revision,'physical_playback':False,'input':'synthetic K segmented PCM only; no human recordings'}
 stop=asyncio.Event();sampler=None
 async def sample():
  while not stop.is_set():
   t=time.monotonic();result['load_samples'].append({'at':t,'load':os.getloadavg()});await asyncio.sleep(.1)
   result['load_samples'][-1]['cycle_ms']=(time.monotonic()-t)*1000
 def save():
  result.update(additional_api_usd=(ledger.used_micro_usd()-initial)/1e6,provider_observations=list(c.provider.observations),native_rows=native_rows,scheduler=voice.metrics)
  (folder/'observations.json').write_text(json.dumps(result,indent=2)+'\n')
 async def work():
  nonlocal worker,sampler,active
  worker=Process('hindsight',directory,logs,'guarded_worker.py');sampler=asyncio.create_task(sample())
  t=time.monotonic();await asyncio.to_thread(send,{'op':'initialize'});result['memory_startup_ms']=(time.monotonic()-t)*1000
  t=time.monotonic();await voice.prepare();result['K_startup_ms']=(time.monotonic()-t)*1000
  t=time.monotonic();await asyncio.to_thread(asr.prepare);result['asr_startup_ms']=(time.monotonic()-t)*1000;result['asr_profile']=asr.profile
  session=None
  for number,item in enumerate(cases,1):
   active=item
   if item['session']!=session:
    c.stop();scope.clear();scope.update(revision=revision,task={'actual_speaker_id':item['speaker'],'people':fixture['people'],'audience_ids':['a','b','c','d'],'conversation_at':'2026-09-20T12:00:00Z','catalogue':item['catalogue']})
    c.start('synthetic');session=item['session']
   with wave.open(item['path'],'rb') as w:
    if (w.getnchannels(),w.getsampwidth(),w.getframerate())!=(1,2,16000):raise ValueError('Bad input PCM')
    pcm=w.readframes(w.getnframes())
   before=await asyncio.to_thread(probe)
   if not before['ok']:raise ValueError('Network preflight failed')
   row={'id':item['id'],'category':item['category'],'oracle':item['oracle'],'expected_text':item['text'],'session':session,'chunks':[],'followup':number%2==0,'history_before':list(c.history),'load_before':os.getloadavg()}
   result['cases'].append(row);start=time.monotonic();wall_start=clock()
   try:
    c.feed('synthetic',{'events':[{'type':'speech_started','utterance':number}]})
    decoded=await asyncio.to_thread(asr.decode,pcm,time.monotonic()+3)
    row['asr']=asdict(decoded);row['asr_ms']=(time.monotonic()-start)*1000
    c.feed('synthetic',{'events':[{'type':'recognition','utterance':number,'text':decoded.text,'final':True,'recognition_id':item['id'],'job_age_ms':row['asr_ms']}]})
    if c.input_rejection or c.controller.token is None or c.accepted_utterance!=number:raise ValueError('Unaccepted local recognition')
    rid=c.controller.token.response_id;row['response_id']=rid
    async with asyncio.timeout(65):
     while c.completed_response_id!=rid:
      if c.failure:raise ValueError(str(c.failure))
      if c.audio:
       a=c.audio;wav=c.audio_bytes('synthetic',rid,a['sequence']);validate_wave(wav,24000)
       path=audio_dir/f"{item['id']}-{a['sequence']}.wav";path.write_bytes(wav)
       row['chunks'].append({'sequence':a['sequence'],'text':a['text'],'ready_ms':(a['ready_at']-start)*1000,'duration_ms':a['duration_ms'],'audio_path':str(path),'sha256':hashlib.sha256(wav).hexdigest()})
       body={'response_id':rid,'sequence':a['sequence']};assert c.command('synthetic','started',body);assert c.command('synthetic','played',body)
      await asyncio.sleep(.005)
    row.update(first_audio_ms=row['chunks'][0]['ready_ms'],text=c.last_reply,history=list(c.history),text_reconstructed=''.join(x['text'] for x in row['chunks'])==c.last_reply,played_history_matches=c.history[-1]=={'role':'assistant','content':c.last_reply},completed=True)
   except Exception as e:row['error']=type(e).__name__+': '+str(e)
   end=clock();after=await asyncio.to_thread(probe)
   row.update(network={'before':before,'after':after,'start':wall_start,'end':end,**qualified(before,after,wall_start,end)},load_after=os.getloadavg(),metrics=list(c.metrics))
   save();print(json.dumps({'id':item['id'],'recognized':row.get('asr',{}).get('text'),'first_audio_ms':row.get('first_audio_ms'),'text':row.get('text'),'error':row.get('error')}),flush=True)
 try:await asyncio.wait_for(work(),plan['limits']['maximum_wall_seconds'])
 except Exception as e:result['errors'].append(type(e).__name__+': '+str(e))
 finally:
  stop.set()
  if sampler:await sampler
  await c.close();await asyncio.to_thread(asr.close)
  if worker:worker.stop()
  save();ledger.close()
 print(json.dumps({'awaiting_review':str(folder),'errors':result['errors']}),flush=True)

if __name__=='__main__':asyncio.run(run())
