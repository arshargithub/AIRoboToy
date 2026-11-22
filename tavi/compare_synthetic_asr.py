"""Same-file local controls for the completed synthetic cloud probe."""
import asyncio
import json
from pathlib import Path
import time
import wave

from .experiment_workflow import begin,finish,audit
from .mlx_final_asr import MlxFinalASR
from .streaming_final_asr import StreamingFinalASR
from .speech_check import score


async def run():
    folder,plan=begin('experiments/streaming-asr/synthetic-pair-protocol-v1.json')
    corpus=json.loads(Path(plan['inputs'][0]).read_text())
    report={'rows':[],'completed':False};fault=None
    try:
        for name,factory in [('mlx_turbo',MlxFinalASR),('moonshine',StreamingFinalASR)]:
            worker=factory()
            try:
                await asyncio.to_thread(worker.prepare)
                for case in corpus['cases']:
                    with wave.open(case['wav']) as w:pcm=w.readframes(w.getnframes())
                    began=time.monotonic();result=await asyncio.to_thread(worker.decode,pcm,began+15)
                    report['rows'].append({'model':name,'case':case['id'],'text':result.text,
                        'roundtrip_ms':(time.monotonic()-began)*1000,'profile':worker.profile,
                        **score(case['expected'],result.text)})
                print(name,'six synthetic files completed',flush=True)
            finally:await asyncio.to_thread(worker.close)
        report['completed']=True
    except Exception as error:fault=type(error).__name__;report['error']=fault
    output=folder/'results.json';output.write_text(json.dumps(report,indent=2)+'\n')
    metrics={'local_observations':len(report['rows']),'worker_faults':int(fault is not None)}
    result=finish(folder,metrics,artifacts=[output],completed=report['completed'],error=fault)
    print(json.dumps({'run':str(folder),'decision':result['decision'],'audit':audit(folder)}))


if __name__=='__main__':asyncio.run(run())
