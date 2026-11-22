"""Zero-paid local recall/K stage diagnostic; no microphone or playback.

Concurrent recall plus saved-text synthesis is a contention probe, not a feasible
schedule for a new live answer. ps CPU values/load averages are coarse telemetry,
not instantaneous GPU occupancy or proof of thermal throttling.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time

from experiments.memory.runtime import ROOT,SSD,require_ssd
from experiments.memory.pilot import Process
from experiments.memory.context_envelope import pack
from tavi.local_speech import LocalSpeech
from tavi.sentence_chunks import SentenceChunks
from tavi.storage import Store
from tavi.experiment_workflow import begin,finish,audit

async def run():
    import httpx,tiktoken
    require_ssd();os.environ['TIKTOKEN_CACHE_DIR']=str(SSD/'models/tiktoken')
    folder,plan=begin(ROOT/'experiments/memory/local-stage-protocol.json',run_root=SSD/'runs/scored')
    print(json.dumps({'run':str(folder),'audit':audit(folder)}),flush=True)
    inputs=json.loads((ROOT/'experiments/memory/local-stage-input.json').read_text())
    fixture=json.loads((ROOT/'experiments/memory/decision-v2-input.json').read_text())
    settings=json.loads((ROOT/'experiments/memory/voice-integration-input.json').read_text())
    directory=Path(settings['native_directory']);db=sqlite3.connect(f'file:{directory}/source-ledger.sqlite3?mode=ro',uri=True)
    sources=[json.loads(r[0]) for r in db.execute('SELECT body FROM episodes WHERE complete=1 AND deleted=0')];db.close()
    expected=[e for e in fixture['episodes'] if e['speaker_id']!='unknown']
    if sorted(sources,key=lambda s:s['id'])!=sorted(expected,key=lambda s:s['id']):raise ValueError('Source generation changed')
    logs=folder/'logs';logs.mkdir();worker=None;voice=LocalSpeech('kokoro-k-mlx')
    store=Store(ROOT/'.tavi/simulation/simulation.sqlite3');initial=store.used_micro_usd()
    result={'rows':[],'samples':[],'errors':[],'physical_playback':False,'cpu_count':os.cpu_count()}
    stop=asyncio.Event();sampler=None;enc=tiktoken.get_encoding('o200k_base')
    def health():
        value=httpx.get('http://127.0.0.1:8790/health',timeout=3,trust_env=False).json()
        if value['paid_enabled']:raise ValueError('Paid gateway must be disabled')
        return value
    def save(): (folder/'observations.json').write_text(json.dumps(result,indent=2)+'\n')
    async def sample():
        while not stop.is_set():
            before=time.monotonic()
            pids=[p for p in [worker.process.pid if worker else None,voice.process.pid if voice.process else None] if p]
            def ps():
                if not pids:return ''
                return subprocess.check_output(['/bin/ps','-p',','.join(map(str,pids)),'-o','pid=,pcpu=,rss='],text=True,timeout=2)
            try:processes=await asyncio.to_thread(ps)
            except Exception as e:processes=type(e).__name__
            result['samples'].append({'at':before,'load':os.getloadavg(),'process_cpu_rss':processes})
            await asyncio.sleep(.25)
            result['samples'][-1]['sample_cycle_ms']=(time.monotonic()-before)*1000
    def send(request):
        value=worker.send(request,timeout=45)
        if not value['ok']:raise ValueError(value['error'])
        return value['result']
    async def recall(case):
        start=time.monotonic();native=await asyncio.to_thread(send,{'op':'query','question':case,'people':fixture['people']})
        queried=time.monotonic();packed=pack('hindsight',native['native_context'],sources,case['audience_ids'],enc)
        return {'start':start,'query_ms':(queried-start)*1000,'pack_ms':(time.monotonic()-queried)*1000,
                'total_ms':(time.monotonic()-start)*1000,'facts':packed['selected_facts'],'native_retrieval_ms':native.get('retrieval_ms')}
    async def speak(text):
        start=time.monotonic();audio=await voice.synthesize(text)
        return {'start':start,'ms':(time.monotonic()-start)*1000,'duration_ms':audio.duration_ms,
                'sha256':hashlib.sha256(audio.wav).hexdigest(),'characters':len(text)}
    async def work():
        nonlocal worker,sampler
        result['health_before']=await asyncio.to_thread(health)
        worker=Process('hindsight',directory,logs,'guarded_worker.py');sampler=asyncio.create_task(sample())
        start=time.monotonic();await asyncio.to_thread(send,{'op':'initialize'});result['recall_initialize_ms']=(time.monotonic()-start)*1000
        start=time.monotonic();await voice.prepare();result['voice_startup_including_warmup_ms']=(time.monotonic()-start)*1000
        for repeat in range(2):
            cases=inputs['cases'] if repeat==0 else list(reversed(inputs['cases']))
            for index,row in enumerate(cases):
                case=next(c for c in fixture['cases'] if c['id']==row['id'])
                splitter=SentenceChunks();parts=splitter.feed(row['text'])+splitter.finish()
                for mode in (['serial','concurrent'] if (index+repeat)%2==0 else ['concurrent','serial']):
                    start=time.monotonic();before=os.getloadavg()
                    if mode=='serial':a=await recall(case);b=await speak(parts[0])
                    else:a,b=await asyncio.gather(recall(case),speak(parts[0]))
                    observation={'id':row['id'],'repeat':repeat,'mode':mode,'start':start,'end':time.monotonic(),
                        'load_before':before,'load_after':os.getloadavg(),'recall':a,'voice':b,'first_chunk':parts[0],
                        'total_characters':len(row['text']),'partition_exact':''.join(parts)==row['text']}
                    result['rows'].append(observation);save()
                    print(json.dumps({'id':row['id'],'repeat':repeat,'mode':mode,'recall_ms':round(a['total_ms']),'voice_ms':round(b['ms'])}),flush=True)
        result['health_after']=await asyncio.to_thread(health)
    try:await asyncio.wait_for(work(),300)
    except Exception as e:result['errors'].append(type(e).__name__+': '+str(e))
    finally:
        stop.set()
        if sampler:await sampler
        await voice.close()
        if worker:worker.stop()
        result['additional_api_usd']=(store.used_micro_usd()-initial)/1e6;store.close();save()
    metrics={'rows_complete':len(result['rows']),'collection_errors':len(result['errors']),
             'partition_errors':sum(not r['partition_exact'] for r in result['rows']),
             'telemetry_samples':len(result['samples']),'additional_api_usd':result['additional_api_usd'],
             'gateway_new_calls':result.get('health_after',{}).get('calls',-1)-result.get('health_before',{}).get('calls',0)}
    record=finish(folder,metrics,artifacts=[folder/'observations.json'],completed=not result['errors'],error='; '.join(result['errors']) or None)
    print(json.dumps({'metrics':metrics,'audit':audit(folder)}),flush=True)

if __name__=='__main__':asyncio.run(run())
