"""Frozen local-only batch/streaming comparison alongside real K synthesis."""
import asyncio
import json
from pathlib import Path
import statistics
import time
import wave

from .addressing import ADDRESS
from .benchmark_mlx_asr import percentile,used_budget
from .experiment_workflow import begin,finish,audit
from .local_speech import LocalSpeech,validate_wave
from .speech_check import words,score
from .streaming_final_asr import StreamingFinalASR


def meaning_present(text,rule):
    tokens=words(text)
    return all(word in tokens for word in rule['required']) and not any(word in tokens for word in rule['forbidden'])


async def run():
    folder,plan=begin('experiments/streaming-asr/protocol-v1.json')
    corpus=json.loads(Path(plan['inputs'][0]).read_text())['clips'];by_id={c['id']:c for c in corpus}
    report={'experiment_id':plan['experiment_id'],'rows':[],'profiles':[],
            'initial_api_usd':used_budget(),'K_jobs':0,'completed':False}
    voice=LocalSpeech('kokoro-k-mlx');load_task=None;stop=asyncio.Event();failures=0;error=None
    def save():(folder/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    async def load():
        while not stop.is_set():
            audio=await voice.synthesize('A little fox found a silver boat beside the lake. It sailed across the water and brought a lost duckling home.')
            validate_wave(audio.wav,24000);report['K_jobs']+=1
    async def trial(worker,clip,condition):
        with wave.open(clip['windows'][0]['wav']) as wav:pcm=wav.readframes(wav.getnframes())
        began=time.monotonic();deadline=began+(len(pcm)/32000+15 if worker.paced else 15)
        value=await asyncio.to_thread(worker.decode,pcm,deadline)
        row={'clip':clip['id'],'condition':condition,'roundtrip_ms':(time.monotonic()-began)*1000,
             'text':value.text,'timing':value.timing,'confidence':value.confidence}
        if 'expected' in clip:row['reference_diagnostic']=score(clip['expected'],value.text)
        if clip['id'] in plan['configuration']['meaning_checks']:
            row['critical_slots_present']=meaning_present(value.text,plan['configuration']['meaning_checks'][clip['id']])
        report['rows'].append(row);save()
    try:
        worker=StreamingFinalASR(mode='batch')
        try:
            started=time.monotonic();await asyncio.to_thread(worker.prepare)
            report['profiles'].append({'condition':'batch','prepare_ms':(time.monotonic()-started)*1000,'profile':worker.profile})
            for clip in corpus:await trial(worker,clip,'batch')
            print('Batch development pass:',len(corpus),'windows completed',flush=True)
        finally:await asyncio.to_thread(worker.close)
        await voice.prepare()
        for condition in ('paced_quiet','paced_K_busy'):
            worker=StreamingFinalASR(mode='stream',paced=True)
            try:
                started=time.monotonic();await asyncio.to_thread(worker.prepare)
                report['profiles'].append({'condition':condition,'prepare_ms':(time.monotonic()-started)*1000,'profile':worker.profile})
                if condition=='paced_K_busy':
                    load_task=asyncio.create_task(load())
                    async with asyncio.timeout(16):
                        while not voice.inflight:
                            if load_task.done():await load_task
                            await asyncio.sleep(.005)
                for key in plan['configuration']['paced_clips']:
                    await trial(worker,by_id[key],condition)
                    if load_task and load_task.done():await load_task
                if condition=='paced_quiet':
                    for key in plan['configuration']['after_idle_clips']:
                        await asyncio.sleep(10)
                        await trial(worker,by_id[key],'paced_after_idle')
                print(condition,'completed',flush=True)
            finally:
                if load_task:
                    stop.set();load_task.cancel();await asyncio.gather(load_task,return_exceptions=True);load_task=None
                await asyncio.to_thread(worker.close)
        report['final_api_usd']=used_budget()
        if report['initial_api_usd']!=report['final_api_usd']:raise ValueError('API ledger changed during local-only run')
        report['completed']=True
    except Exception as exc:
        failures+=1;error=type(exc).__name__;report['error']=error
    finally:
        if load_task:load_task.cancel();await asyncio.gather(load_task,return_exceptions=True)
        await voice.close();save()
    batch=[r for r in report['rows'] if r['condition']=='batch']
    paced=[r for r in report['rows'] if r['condition'].startswith('paced')]
    positives=[c for c in corpus if c.get('target')=='paprika']
    negatives=[c for c in corpus if c.get('category')=='confusable']
    lookup={r['clip']:r for r in batch}
    meaningful=[r for r in paced if 'critical_slots_present' in r and r['condition']!='paced_after_idle']
    metrics={'worker_failures':failures,'batch_windows':len(batch),'paced_windows':len(paced),
        'clean_stream_critical_successes':sum(r['critical_slots_present'] for r in meaningful),
        'name_positives_preserved':sum(bool(ADDRESS.match(lookup[c['id']]['text'])) for c in positives if c['id'] in lookup),
        'confusable_false_addresses':sum(bool(ADDRESS.match(lookup[c['id']]['text'])) for c in negatives if c['id'] in lookup),
        'batch_p95_ms':percentile([r['roundtrip_ms'] for r in batch],.95) if batch else None,
        'paced_p95_final_tail_ms':percentile([r['timing']['forced_stop_flush_ms'] for r in paced],.95) if paced else None,
        'paced_max_backlog_ms':max((r['timing']['max_pacing_lag_ms'] for r in paced),default=None),
        'K_completed_valid_jobs':report['K_jobs'],
        'api_spend_unchanged':report.get('final_api_usd')==report['initial_api_usd']}
    report['metrics']=metrics;save()
    record=finish(folder,metrics,artifacts=[folder/'results.json'],completed=report['completed'],error=error)
    print(json.dumps({'run':str(folder),'metrics':metrics,'decision':record['decision'],'audit':audit(folder)},indent=2),flush=True)


if __name__=='__main__':asyncio.run(run())
