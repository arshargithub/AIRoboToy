"""Bounded ABA check of idle-worker residency, using saved PCM only."""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import time
import wave

from .benchmark_mlx_asr import used_budget
from .local_speech import LocalSpeech
from .mlx_final_asr import MlxFinalASR


async def run():
    protocol=Path('experiments/asr-mlx/residency-protocol.json')
    plan=json.loads(protocol.read_text());source=Path(plan['source'])
    manifest=json.loads(source.read_text());cases=manifest['runs'][0]['recognitions']
    cases=[e for e in cases if e['utterance'] in plan['clips']]
    assert len(cases)==3
    folder=Path('.tavi/turbo-residency')/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder.mkdir(parents=True)
    primary=MlxFinalASR();extra=MlxFinalASR();voice=LocalSpeech('kokoro-k-mlx')
    report={'protocol':plan,'protocol_sha256':hashlib.sha256(protocol.read_bytes()).hexdigest(),
        'source_sha256':manifest['source_sha256'],'rows':[],'completed':False,
        'initial_budget_usd':used_budget()}
    try:
        await asyncio.to_thread(primary.prepare)
        for condition in plan['conditions_in_order']:
            if condition=='extra_idle_ASR_and_K':
                await asyncio.to_thread(extra.prepare)
                await voice.synthesize('A tiny fox found a silver key beside the river.')
            elif condition=='single_ASR_again':
                await asyncio.to_thread(extra.close)
                await voice.close()
            for repeat in range(2):
                for event in cases[repeat:]+cases[:repeat]:
                    with wave.open(event['asr_input_wav']) as w:pcm=w.readframes(w.getnframes())
                    began=time.monotonic()
                    result=await asyncio.to_thread(primary.decode,pcm,began+15)
                    report['rows'].append({'condition':condition,'repeat':repeat+1,'utterance':event['utterance'],
                        'roundtrip_ms':(time.monotonic()-began)*1000,'text':result.text})
                    (folder/'report.json').write_text(json.dumps(report,indent=2)+'\n')
            values=[r['roundtrip_ms'] for r in report['rows'] if r['condition']==condition]
            print(condition,'median',round(statistics.median(values)),'max',round(max(values)),'ms',flush=True)
        report['final_budget_usd']=used_budget()
        assert report['initial_budget_usd']==report['final_budget_usd']
        report['completed']=True
    finally:
        await asyncio.to_thread(primary.close)
        await asyncio.to_thread(extra.close)
        await voice.close()
        (folder/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'report':str(folder/'report.json'),'completed':report['completed']}),flush=True)


if __name__=='__main__':asyncio.run(run())
