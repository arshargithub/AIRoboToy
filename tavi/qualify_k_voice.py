"""Real K worker timing/cancellation smoke; synthetic text, no cloud or playback."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import statistics
import time

from .benchmark_conversation_voice import CASES
from .local_speech import LocalSpeech


async def run(resume=False,backend='kokoro-k'):
    root=Path('.tavi/k-live-qualification');root.mkdir(parents=True,exist_ok=True)
    path=root/('mlx-worker-report.json' if backend.endswith('-mlx') else 'worker-report.json')
    report={'scope':'Synthetic native worker check; no ASR, microphone, cloud, playback or end-to-end latency verdict',
            'backend':backend,'threads':None if backend.endswith('-mlx') else 2,'repeats':3,'reply_timeout_seconds':16,
            'api_spend_usd':0,'rows':[],'completed':False}
    if resume:
        previous=json.loads(path.read_text())
        if len(previous['rows'])!=18 or previous['backend']!='kokoro-k' or previous['threads']!=2:
            raise ValueError('No matching completed timing suite to resume')
        report['rows']=previous['rows'];report['initialization_ms']=previous['initialization_ms']
        report['resumed_measurements_after_invalid_bitidentity_assertion']=True
    def save():path.write_text(json.dumps(report,indent=2)+'\n')
    voice=LocalSpeech(backend)
    try:
        start=time.perf_counter();await voice.prepare()
        if not resume:report['initialization_ms']=(time.perf_counter()-start)*1000
        for repeat in ([] if resume else range(3)):
            for key,parts in CASES[repeat:]+CASES[:repeat]:
                start=time.perf_counter();audio=await voice.synthesize(''.join(parts));elapsed=(time.perf_counter()-start)*1000
                (root/f'{key}-{repeat+1}-{backend}-worker.wav').write_bytes(audio.wav)
                row={'case':key,'repeat':repeat+1,'text':''.join(parts),'preparation_ms':elapsed,'duration_ms':audio.duration_ms}
                report['rows'].append(row);save();print(key,repeat+1,round(elapsed),'ms',flush=True)
        # This model has RandomNormal/Uniform nodes. Regeneration is not byte-
        # deterministic; lock the actual K style rather than demanding WAV hashes.
        import numpy as np
        from .kokoro_k import ROOT
        approved_styles=np.fromfile('.tavi/voice-direction/direction-blends.bin',dtype='<f4').reshape(54,510,256)
        current_styles=np.fromfile(ROOT/'voices.bin',dtype='<f4').reshape(54,510,256)
        np.testing.assert_array_equal(current_styles[0],approved_styles[0])
        report['approved_K_style_embedding_matches']=True
        approved=json.loads(Path('tavi/web/voice-direction-protocol.json').read_text());report['reference_regenerations']=[]
        for trial in approved['trials']:
            if trial['voice']=='K':
                audio=await voice.synthesize(trial['text'])
                report['reference_regenerations'].append({'case':trial['case'],'duration_ms':audio.duration_ms,
                    'generated_sha256':hashlib.sha256(audio.wav).hexdigest(),'audition_sha256':trial['sha256']})
        old=voice.process
        pending=asyncio.create_task(voice.synthesize(''.join(CASES[-1][1])))
        await asyncio.sleep(.15);start=time.perf_counter();pending.cancel()
        try:await pending
        except asyncio.CancelledError:pass
        report['native_cancel_ms']=(time.perf_counter()-start)*1000
        if old.returncode is None or voice.process is not None:raise ValueError('Cancelled native worker survived')
        report['native_process_killed']=True
        speech=await voice.synthesize('A fresh little rocket is ready.')
        report['fresh_worker_after_cancel']=voice.process.pid!=old.pid and speech.duration_ms>0
        times=[r['preparation_ms'] for r in report['rows']]
        report['summary']={'median_preparation_ms':statistics.median(times),'maximum_preparation_ms':max(times),
                           'end_to_end_target_qualified':False}
        report['completed']=True;save();print(json.dumps(report['summary']),flush=True)
    except BaseException as error:
        report['failure_type']=type(error).__name__;save();raise
    finally:await voice.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--resume-measurements',action='store_true')
    p.add_argument('--backend',choices=('kokoro-k','kokoro-k-mlx'),default='kokoro-k')
    args=p.parse_args();asyncio.run(run(args.resume_measurements,args.backend))
