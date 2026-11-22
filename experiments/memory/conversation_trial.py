"""Fictional fresh recall/native-text/K through existing conversation controller.

No microphone or audible playback. Ordered STARTED/PLAYED receipts are simulated
and accelerated; actual first readiness includes recall and a new connection.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time

from experiments.memory.runtime import ROOT,SSD,require_ssd
from experiments.memory.pilot import Process
from experiments.memory.context_envelope import pack
from experiments.memory.conversation_adapter import MemoryTextProvider
from experiments.memory.native_voice_trial import Envelope
from experiments.memory.network_window import probe,clock,qualified
from tavi.chunked_conversation import ChunkedConversation
from tavi.local_speech import LocalSpeech,validate_wave
from tavi.storage import Store
from tavi.experiment_workflow import begin,audit

async def run(protocol=ROOT/'experiments/memory/conversation-protocol.json'):
    import tiktoken
    require_ssd();os.environ['TIKTOKEN_CACHE_DIR']=str(SSD/'models/tiktoken')
    folder,plan=begin(protocol,run_root=SSD/'runs/scored')
    print(json.dumps({'run':str(folder),'audit':audit(folder)}),flush=True)
    fixture=json.loads((ROOT/'experiments/memory/decision-v2-input.json').read_text())
    settings=json.loads((ROOT/'experiments/memory/voice-integration-input.json').read_text())
    inputs=json.loads((ROOT/'experiments/memory/conversation-input.json').read_text())
    directory=Path(settings['native_directory'])
    db=sqlite3.connect(f'file:{directory}/source-ledger.sqlite3?mode=ro',uri=True)
    sources=[json.loads(r[0]) for r in db.execute('SELECT body FROM episodes WHERE complete=1 AND deleted=0')];db.close()
    expected=[e for e in fixture['episodes'] if e['speaker_id']!='unknown']
    if sorted(sources,key=lambda s:s['id'])!=sorted(expected,key=lambda s:s['id']):raise ValueError('Native source generation changed')
    source_hash=hashlib.sha256(json.dumps(sources,sort_keys=True).encode()).hexdigest()
    logs=folder/'logs';logs.mkdir();audio_dir=folder/'audio';audio_dir.mkdir()
    worker=Process('hindsight',directory,logs,'guarded_worker.py')
    def send(request):
        result=worker.send(request,timeout=60)
        if not result['ok']:raise ValueError(result['error'])
        return result['result']
    class TrialEnvelope(Envelope):
        def reserve(self,key,amount,cap):
            if self.calls>=6 or self.store.used_micro_usd()+amount>self.initial+2_000_000:
                raise ValueError('Controller trial spending bound')
            super().reserve(key,amount,cap)
    store=Store(ROOT/'.tavi/simulation/simulation.sqlite3');envelope=TrialEnvelope(store)
    scope={};enc=tiktoken.get_encoding('o200k_base');native_rows=[]
    async def recall(task):
        query={'id':scope['case_id'],'asker':task['actual_speaker_id'],'audience_ids':task['audience_ids'],
               'text':task['question'],'at':task['conversation_at'],'catalogue':task['catalogue']}
        native=await asyncio.to_thread(send,{'op':'query','question':query,'people':task['people']})
        packed=pack('hindsight',native['native_context'],sources,task['audience_ids'],enc)
        native_rows.append({'case_id':query['id'],'native':native,'packed':packed})
        return {'evidence':json.loads(packed['context']),'sources':sources}
    provider=MemoryTextProvider(envelope,scope=lambda:scope,recall=recall)
    voice=LocalSpeech('kokoro-k-mlx')
    c=ChunkedConversation(store,provider=provider,speech=voice,context_revision=lambda:scope)
    result={'cases':[],'errors':[],'source_generation_sha256':source_hash,'physical_playback':False,
            'receipt_timing':'simulated accelerated; not acoustic or queue scheduling evidence'}
    def save():
        result.update(provider_observations=list(provider.observations),native_rows=native_rows,
                      additional_spent_reserved_usd=(store.used_micro_usd()-envelope.initial)/1e6)
        (folder/'observations.json').write_text(json.dumps(result,indent=2)+'\n')
    async def work():
        await asyncio.to_thread(send,{'op':'initialize'})
        start=time.monotonic();await voice.prepare();result['voice_prepare_ms']=(time.monotonic()-start)*1000
        for case_id in inputs['case_ids']:
            case=next(r for r in fixture['cases'] if r['id']==case_id)
            scope.clear();scope.update(case_id=case_id,revision=source_hash,task={
                'actual_speaker_id':case['asker'],'people':fixture['people'],'audience_ids':case['audience_ids'],
                'conversation_at':case['at'],'catalogue':case['catalogue']})
            before=await asyncio.to_thread(probe)
            if not before['ok']:raise ValueError('Network preflight failed')
            c.start('synthetic');start=time.monotonic();wall_start=clock()
            text='Paprika, '+case['text']
            c.feed('synthetic',{'events':[{'type':'speech_started','utterance':1},
                {'type':'recognition','utterance':1,'text':text,'final':True}]})
            rid=c.controller.token.response_id
            row={'id':case_id,'oracle':case['oracle'],'chunks':[],'first_audio_ms':None};result['cases'].append(row)
            async with asyncio.timeout(65):
                while c.completed_response_id!=rid:
                    if c.failure:raise ValueError('Controller failure: '+json.dumps(c.failure))
                    if c.audio:
                        a=c.audio;ready=(time.monotonic()-start)*1000
                        if row['first_audio_ms'] is None:row['first_audio_ms']=ready
                        wav=c.audio_bytes('synthetic',rid,a['sequence']);validate_wave(wav,24000)
                        path=audio_dir/f'{case_id}-{a["sequence"]}.wav';path.write_bytes(wav)
                        row['chunks'].append({'sequence':a['sequence'],'text':a['text'],'duration_ms':a['duration_ms'],
                            'received_ms':ready,'audio_path':str(path),'sha256':hashlib.sha256(wav).hexdigest()})
                        body={'response_id':rid,'sequence':a['sequence']}
                        assert c.command('synthetic','started',body)
                        assert c.command('synthetic','played',body)
                        assert not c.command('synthetic','played',body)
                    await asyncio.sleep(.01)
            end=clock();after=await asyncio.to_thread(probe)
            row.update(text=c.last_reply,history=c.history,metrics=list(c.metrics),
                text_reconstructed=''.join(a['text'] for a in row['chunks'])==c.last_reply,
                played_history_matches=c.history[-1]=={'role':'assistant','content':c.last_reply},
                network={'before':before,'after':after,'start':wall_start,'end':end,**qualified(before,after,wall_start,end)})
            save();print(json.dumps({'id':case_id,'first_audio_ms':row['first_audio_ms'],'text':row['text']}),flush=True)
            c.stop()
    try:await asyncio.wait_for(work(),plan['limits']['maximum_wall_seconds'])
    except Exception as e:result['errors'].append(type(e).__name__+': '+str(e));save()
    finally:
        await c.close();worker.stop();save();store.close()
    print(json.dumps({'awaiting_review':str(folder),'errors':result['errors']}),flush=True)

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--protocol',default=str(ROOT/'experiments/memory/conversation-protocol.json'))
    asyncio.run(run(Path(parser.parse_args().protocol)))
