"""Frozen local timing attribution and memory-configuration screen."""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import time
import urllib.request
import wave

from .benchmark_mlx_asr import used_budget
from .mlx_final_asr import MlxFinalASR


async def run(mode):
    protocol=Path('experiments/asr-mlx/performance-protocol.json')
    plan=json.loads(protocol.read_text())
    with urllib.request.urlopen('http://127.0.0.1:8766/api/conversation/diagnostics',timeout=3) as response:
        if json.load(response)['lease_active']:raise ValueError('Do not profile during active capture')
    manifest=json.loads(Path(plan['source']).read_text())
    clips=[e for e in manifest['runs'][0]['recognitions'] if e['utterance'] in plan['clips']]
    assert len(clips)==3
    folder=Path('.tavi/asr-performance')/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder.mkdir(parents=True)
    report={'protocol':plan,'protocol_sha256':hashlib.sha256(protocol.read_bytes()).hexdigest(),
        'source_sha256':manifest['source_sha256'],'mode':mode,'rows':[],'profiles':[],
        'initial_budget_usd':used_budget(),'completed':False}
    configs=[(256,0,False),(256,0,True)] if mode=='stages' else [(c,w,False) for c,w in plan['memory_orders']]
    def save():(folder/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    try:
        for cycle,(cache,wired,profile) in enumerate(configs,1):
            worker=MlxFinalASR(cache_mib=cache,wired_mib=wired,profile_stages=profile)
            try:
                await asyncio.to_thread(worker.prepare)
                report['profiles'].append(worker.profile)
                for repeat in range(2 if mode=='stages' else 1):
                    order=clips[repeat:]+clips[:repeat]
                    for clip in order:
                        with wave.open(clip['asr_input_wav']) as w:pcm=w.readframes(w.getnframes())
                        began=time.monotonic()
                        result=await asyncio.to_thread(worker.decode,pcm,began+15)
                        report['rows'].append({'cycle':cycle,'cache_mib':cache,'wired_mib':wired,
                            'profiled':profile,'repeat':repeat+1,'utterance':clip['utterance'],
                            'roundtrip_ms':(time.monotonic()-began)*1000,
                            'text':result.text,'confidence':result.confidence,'timing':result.timing})
                        save()
                times=[r['roundtrip_ms'] for r in report['rows'] if r['cycle']==cycle]
                print('cycle',cycle,'cache',cache,'wired',wired,'profiled',profile,
                      'median',round(statistics.median(times)),'max',round(max(times)),'ms',flush=True)
                if profile:
                    for stage in ('mel_ms','encoder_ms','token_loop_ms'):
                        values=[r['timing']['stages'].get(stage,0) for r in report['rows'] if r['cycle']==cycle]
                        print(stage,'median',round(statistics.median(values)),'ms',flush=True)
            finally:await asyncio.to_thread(worker.close)
        report['final_budget_usd']=used_budget()
        assert report['initial_budget_usd']==report['final_budget_usd']
        report['completed']=True
    finally:save()
    print(json.dumps({'report':str(folder/'report.json'),'completed':report['completed']}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=('stages','memory'))
    asyncio.run(run(parser.parse_args().mode))
