"""Frozen saved-audio comparison, including actual concurrent K synthesis.

No microphone, speakers or cloud. Private transcripts remain under .tavi/. Each
model runs in an isolated offline worker; the live app is never reconfigured.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import statistics
import time
from uuid import uuid4

from .benchmark_conversation_voice import CASES
from .local_speech import LocalSpeech
from .speech_check import score

PROTOCOL=Path('experiments/asr-mlx/protocol.json')


def percentile(values,p):
    return sorted(values)[max(0,math.ceil(len(values)*p)-1)] if values else None


def used_budget():
    db=sqlite3.connect('file:.tavi/simulation/simulation.sqlite3?mode=ro',uri=True)
    try:return db.execute('SELECT COALESCE(SUM(COALESCE(actual,reserved)),0) FROM spending').fetchone()[0]/1e6
    finally:db.close()


class Worker:
    def __init__(self,model,folder):self.model=model;self.folder=folder;self.process=None;self.stderr=None
    async def prepare(self):
        executable='.venv-tavi/bin/python' if self.model=='cpu_base.en' else '.venv-asr-mlx/bin/python'
        env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'LANG':'en_US.UTF-8',
             'HF_HUB_OFFLINE':'1','HF_HUB_DISABLE_TELEMETRY':'1','HF_HUB_DISABLE_IMPLICIT_TOKEN':'1',
             'TRANSFORMERS_OFFLINE':'1','TOKENIZERS_PARALLELISM':'false'}
        self.stderr=(self.folder/(self.model+'.stderr.log')).open('wb')
        began=time.perf_counter()
        self.process=await asyncio.create_subprocess_exec(executable,'-m','tavi.asr_compare_worker','--model',self.model,
            stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=self.stderr,env=env,limit=2_000_000)
        line=await asyncio.wait_for(self.process.stdout.readline(),120)
        if not line:raise ValueError('ASR worker ended at startup; see private stderr log')
        ready=json.loads(line)
        if ready.get('ready') is not True:raise ValueError('Invalid worker greeting')
        ready['process_start_to_ready_ms']=(time.perf_counter()-began)*1000
        return ready
    async def request(self,window,prompt):
        request_id=uuid4().hex
        started=time.perf_counter()
        self.process.stdin.write((json.dumps({'id':request_id,'wav':window['wav'],'prompt':prompt})+'\n').encode())
        await self.process.stdin.drain()
        line=await asyncio.wait_for(self.process.stdout.readline(),30)
        if not line:raise ValueError('ASR worker ended during decoding')
        result=json.loads(line)
        if result.get('id')!=request_id:raise ValueError('Mismatched ASR result')
        if result.get('error'):raise ValueError('ASR decode failed: '+result['error'])
        result.update(start=started,end=time.perf_counter(),roundtrip_ms=(time.perf_counter()-started)*1000)
        return result
    async def close(self):
        if self.process is not None:
            if self.process.returncode is None:
                self.process.kill()
            await self.process.wait()
        if self.stderr:self.stderr.close()


async def run(folder,models,*,protocol_path=PROTOCOL,accuracy=True,timing_mode='hinted'):
    folder.mkdir(parents=True,exist_ok=False)
    plan=json.loads(protocol_path.read_text());corpus_path=Path('.tavi/asr-mlx-comparison/corpus-v1/manifest.json')
    corpus=json.loads(corpus_path.read_text());clips=corpus['clips'];timing=[c for c in clips if c['timing']]
    voice=LocalSpeech('kokoro-k-mlx');k_rows=[];stop_k=asyncio.Event();k_task=None
    report={'schema_version':1,'protocol':plan,'protocol_sha256':hashlib.sha256(protocol_path.read_bytes()).hexdigest(),
            'corpus_sha256':hashlib.sha256(corpus_path.read_bytes()).hexdigest(),'corpus':corpus,
            'created_at':datetime.now(timezone.utc).isoformat(),'api_spend_usd':0,
            'initial_budget_usd':used_budget(),'models':{},'rows':[],'K_rows':k_rows,'faults':[],'completed':False,
            'timing_mode':timing_mode,'accuracy_pass_enabled':accuracy,'process_pid':os.getpid()}
    def save():
        tmp=folder/'report.partial.json';tmp.write_text(json.dumps(report,indent=2)+'\n');tmp.replace(folder/'report.json')
    async def k_once(key,parts,**meta):
        start=time.perf_counter();audio=await voice.synthesize(''.join(parts));end=time.perf_counter()
        k_rows.append({'case':key,'start':start,'end':end,'ms':(end-start)*1000,
                       'duration_ms':audio.duration_ms,'rtf':(end-start)*1000/audio.duration_ms,**meta})
    async def k_loop(model):
        n=0
        while not stop_k.is_set():
            key,parts=CASES[n%len(CASES)];await k_once(key,parts,condition='K_busy',model=model);n+=1
    async def end_k():
        nonlocal k_task
        stop_k.set()
        if k_task is not None:
            await asyncio.wait_for(k_task,20);k_task=None
    async def trial(worker,clip,mode,condition,phase,repeat):
        if k_task is not None and k_task.done():await k_task
        outputs=[]
        for window in clip['windows']:outputs.append(await worker.request(window,plan['prompts'][mode]))
        text=' '.join(o['text'] for o in outputs).strip()
        row={'model':worker.model,'clip':clip['id'],'mode':mode,'condition':condition,'phase':phase,'repeat':repeat,
             'text':text,'windows':outputs,'decode_ms':sum(o['decode_ms'] for o in outputs),
             'roundtrip_ms':sum(o['roundtrip_ms'] for o in outputs),**score(clip['expected'],text)}
        report['rows'].append(row)
    try:
        await voice.prepare()
        for repeat in range(3):
            for key,parts in CASES:await k_once(key,parts,condition='K_baseline',repeat=repeat+1)
        save();print('K baseline: 18 synthesis jobs completed',flush=True)
        for model in models:
            worker=Worker(model,folder)
            try:
                model_mode=plan.get('timing_modes',{}).get(model,timing_mode)
                report['models'][model]=await worker.prepare()
                report['models'][model]['timing_mode']=model_mode
                warm=await worker.request(timing[0]['windows'][0],plan['prompts'][model_mode])
                report['models'][model]['cold_first_decode']=warm;save()
                print(model,'loaded; cold decode',round(warm['roundtrip_ms']),'ms',flush=True)
                for condition in plan['condition_order'][model]:
                    if condition=='K_busy':
                        stop_k.clear();k_task=asyncio.create_task(k_loop(model));await asyncio.sleep(.05)
                    phase_start=time.perf_counter()
                    for mode in (('hinted','unhinted') if accuracy else ()):
                        for clip in clips:await trial(worker,clip,mode,condition,'accuracy',1)
                        save();print(model,condition,mode,'47 clips complete',flush=True)
                    for repeat in range(3):
                        order=timing[repeat:]+timing[:repeat]
                        if repeat%2:order=list(reversed(order))
                        for clip in order:await trial(worker,clip,model_mode,condition,'timing',repeat+1)
                    await end_k()
                    phase_end=time.perf_counter();save()
                    rows=[r for r in report['rows'] if r['model']==model and r['condition']==condition and r['phase']=='timing']
                    print(model,condition,'warm median',round(statistics.median(r['roundtrip_ms'] for r in rows)),
                          'p95',round(percentile([r['roundtrip_ms'] for r in rows],.95)),'ms',flush=True)
                    report['models'][model].setdefault('phases',[]).append({'condition':condition,'start':phase_start,'end':phase_end})
            except Exception as error:
                report['faults'].append({'model':model,'type':type(error).__name__})
                print(model,'FAILED',type(error).__name__,'see private evidence',flush=True)
            finally:
                await end_k();await worker.close();save()
        report['final_budget_usd']=used_budget()
        if report['final_budget_usd']!=report['initial_budget_usd']:raise ValueError('Budget ledger changed during local-only comparison')
        report['completed']=not report['faults'];save()
        return report
    finally:
        if k_task is not None:
            stop_k.set();k_task.cancel();await asyncio.gather(k_task,return_exceptions=True)
        await voice.close();save()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models',nargs='+',default=['base.en','small.en','medium.en','turbo','cpu_base.en'])
    parser.add_argument('--output',type=Path)
    parser.add_argument('--protocol',type=Path,default=PROTOCOL)
    parser.add_argument('--timing-only',action='store_true')
    parser.add_argument('--timing-mode',choices=('hinted','unhinted'),default='hinted')
    args=parser.parse_args()
    folder=args.output or Path('.tavi/asr-mlx-comparison')/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    result=asyncio.run(run(folder,args.models,protocol_path=args.protocol,accuracy=not args.timing_only,timing_mode=args.timing_mode))
    print(json.dumps({'report':str(folder/'report.json'),'completed':result['completed'],'rows':len(result['rows']),'faults':result['faults']}))
