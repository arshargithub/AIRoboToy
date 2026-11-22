"""Local native integration evidence; no capture, playback or cloud inference."""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import wave

from .benchmark_mlx_asr import percentile, used_budget
from .benchmark_conversation_voice import CASES
from .inference_schedule import ScheduledSpeech
from .local_speech import LocalSpeech, validate_wave
from .mlx_final_asr import MlxFinalASR


def pcm(clip):
    assert len(clip['windows']) == 1
    with wave.open(clip['windows'][0]['wav']) as w:
        return w.readframes(w.getnframes())


async def run():
    protocol = Path('experiments/asr-mlx/integration-protocol.json')
    plan = json.loads(protocol.read_text())
    source = Path('.tavi/asr-mlx-comparison/20261102T215426916744Z/report.json')
    primary = json.loads(source.read_text())
    references = {r['clip']: r['text'] for r in primary['rows']
                  if r['model']=='turbo' and r['mode']=='unhinted' and r['condition']=='quiet' and r['phase']=='accuracy'}
    clips = primary['corpus']['clips']
    folder = Path('.tavi/turbo-integration') / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder.mkdir(parents=True)
    native = LocalSpeech('kokoro-k-mlx')
    schedule = ScheduledSpeech(native, asyncio.get_running_loop())
    decoder = MlxFinalASR(schedule)
    report = {'protocol':plan, 'protocol_sha256':hashlib.sha256(protocol.read_bytes()).hexdigest(),
              'primary_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
              'initial_budget_usd':used_budget(), 'accuracy':[], 'scheduled':[], 'completed':False}
    def save():
        report['schedule']=dict(schedule.metrics)
        (folder/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    try:
        await schedule.prepare()
        await asyncio.to_thread(decoder.prepare)
        report['profile']=decoder.profile
        for clip in clips:
            start=time.monotonic()
            result=await asyncio.to_thread(decoder.decode,pcm(clip),start+3)
            report['accuracy'].append({'clip':clip['id'],'text':result.text,
                'same_as_primary':result.text==references[clip['id']],
                'roundtrip_ms':(time.monotonic()-start)*1000,'confidence':result.confidence})
            save()
        print('Actual final adapter: 47 saved clips completed',flush=True)
        text=''.join(next(parts for key,parts in CASES if key=='short_story'))
        timing=[c for c in clips if c['timing']]
        for repeat in range(3):
            for clip in timing[repeat:]+timing[:repeat]:
                task=asyncio.create_task(schedule.synthesize(text))
                async with asyncio.timeout(12):
                    while not native.inflight:
                        if task.done(): await task; raise ValueError('K ended before preemption')
                        await asyncio.sleep(.005)
                child=native.process
                before=schedule.metrics['synthesis_preemptions']
                start=time.monotonic()
                result=await asyncio.to_thread(decoder.decode,pcm(clip),start+3)
                elapsed=(time.monotonic()-start)*1000
                audio=await task
                validate_wave(audio.wav,24000)
                assert child.returncode is not None, 'K must be reaped before ASR'
                report['scheduled'].append({'clip':clip['id'],'repeat':repeat+1,
                    'roundtrip_ms':elapsed,'text':result.text,
                    'same_as_primary':result.text==references[clip['id']],
                    'native_K_preempted':schedule.metrics['synthesis_preemptions']==before+1,
                    'native_K_reaped':child.returncode is not None,
                    'resumed_K_valid_WAV':True,'resumed_audio_ms':audio.duration_ms})
                save()
            print('Scheduled K/turbo: repetition',repeat+1,'completed',flush=True)
        times=[r['roundtrip_ms'] for r in report['scheduled']]
        report['summary']={'observations':len(times),'p95_ms':percentile(times,.95),'max_ms':max(times),
            'accuracy_differences':sum(not r['same_as_primary'] for r in report['accuracy']),
            'scheduled_differences':sum(not r['same_as_primary'] for r in report['scheduled']),
            'all_native_K_preempted':all(r['native_K_preempted'] for r in report['scheduled'])}
        report['safety_screen_passed']=(report['summary']['p95_ms']<=2000 and max(times)<=2500
            and report['summary']['accuracy_differences']==0 and report['summary']['scheduled_differences']==0
            and report['summary']['all_native_K_preempted'])
        report['final_budget_usd']=used_budget()
        assert report['initial_budget_usd']==report['final_budget_usd']
        assert not schedule.holds
        report['completed']=True
    finally:
        await asyncio.to_thread(decoder.close)
        await schedule.close()
        save()
    print(json.dumps({'report':str(folder/'report.json'),'summary':report['summary'],
                      'safety_screen_passed':report['safety_screen_passed']}),flush=True)


if __name__=='__main__': asyncio.run(run())
