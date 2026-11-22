"""Paired saved-PCM screen and qualification of encoder-only fast attention."""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import time
import wave

from .benchmark_mlx_asr import used_budget
from .mlx_final_asr import MlxFinalASR


async def run(mode):
    protocol=Path('experiments/asr-mlx/fused-protocol.json')
    plan=json.loads(protocol.read_text())
    fresh=json.loads(Path('.tavi/private-conversation-audio/conversation-faa3159cff7f1877/manifest.json').read_text())
    cases=[{'id':f'fresh-{e["utterance"]}','windows':[{'wav':e['asr_input_wav']}]} for e in fresh['runs'][0]['recognitions']]
    if mode=='screen':cases=[c for c in cases if c['id'] in ('fresh-1','fresh-7','fresh-8')]
    else:cases=json.loads(Path('.tavi/asr-mlx-comparison/corpus-v1/manifest.json').read_text())['clips']+cases
    folder=Path('.tavi/fused-encoder')/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder.mkdir(parents=True)
    report={'protocol':plan,'protocol_sha256':hashlib.sha256(protocol.read_bytes()).hexdigest(),
            'mode':mode,'rows':[],'profiles':[],'initial_budget_usd':used_budget(),'completed':False}
    def save():(folder/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    configurations=('standard','fused','fused','standard') if mode=='screen' else ('standard','fused')
    try:
        for cycle,kind in enumerate(configurations,1):
            worker=MlxFinalASR(encoder_attention=kind)
            try:
                await asyncio.to_thread(worker.prepare);report['profiles'].append(worker.profile)
                for repeat in range(2 if mode=='screen' else 1):
                    for case in cases[repeat:]+cases[:repeat]:
                        assert len(case['windows'])==1
                        with wave.open(case['windows'][0]['wav']) as w:pcm=w.readframes(w.getnframes())
                        began=time.monotonic()
                        result=await asyncio.to_thread(worker.decode,pcm,began+15)
                        report['rows'].append({'cycle':cycle,'encoder':kind,'repeat':repeat+1,'clip':case['id'],
                          'roundtrip_ms':(time.monotonic()-began)*1000,'text':result.text,
                          'confidence':result.confidence,'timing':result.timing})
                        save()
                times=[r['roundtrip_ms'] for r in report['rows'] if r['cycle']==cycle]
                print(kind,'cycle',cycle,'clips',len(times),'median',round(statistics.median(times)),
                      'max',round(max(times)),'ms',flush=True)
            finally:await asyncio.to_thread(worker.close)
        report['final_budget_usd']=used_budget()
        assert report['initial_budget_usd']==report['final_budget_usd']
        report['completed']=True
    finally:save()
    print(json.dumps({'report':str(folder/'report.json'),'completed':report['completed']}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=('screen','accuracy'))
    asyncio.run(run(parser.parse_args().mode))
