"""Paced saved PCM through real VAD/LiveWake, with actual scheduled K load."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import wave

from .acoustics import Silero
from .benchmark_conversation_voice import CASES
from .benchmark_mlx_asr import used_budget
from .inference_schedule import ScheduledSpeech
from .live_wake import LiveWake, WhisperDecoder
from .local_speech import LocalSpeech, validate_wave
from .speech_check import score


async def run():
    source=Path('.tavi/private-conversation-audio/conversation-0f418bb5bce4b3e5/manifest.json')
    manifest=json.loads(source.read_text());recording=manifest['runs'][0]
    with wave.open(recording['microphone_wav']) as w:pcm=w.readframes(w.getnframes())
    folder=Path('.tavi/turbo-integration')/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder.mkdir(parents=True)
    native=LocalSpeech('kokoro-k-mlx');schedule=ScheduledSpeech(native,asyncio.get_running_loop())
    decoder=await asyncio.to_thread(WhisperDecoder,final_model='turbo-mlx',schedule=schedule)
    engine=LiveWake(Silero(Path('.tavi/models/silero_vad.onnx'),wake_backend='off'),decoder)
    report={'scope':__doc__,'source_sha256':manifest['source_sha256'],
            'initial_budget_usd':used_budget(),'events':[],'K_jobs':0,'completed':False}
    stop=asyncio.Event();k_task=None
    async def load():
        while not stop.is_set():
            audio=await schedule.synthesize(''.join(CASES[2][1]));validate_wave(audio.wav,24000)
            report['K_jobs']+=1
    try:
        await schedule.prepare()
        lease=(await asyncio.to_thread(engine.start,'hinted'))['stream_id']
        k_task=asyncio.create_task(load())
        started=time.monotonic();maximum=0
        for seq,offset in enumerate(range(0,len(pcm)+128000,1024)):
            await asyncio.sleep(max(0,started+seq*.032-time.monotonic()))
            frame=pcm[offset:offset+1024].ljust(1024,b'\0')
            began=time.monotonic()
            result=engine.feed(lease,seq,frame)
            maximum=max(maximum,(time.monotonic()-began)*1000)
            report['events'].extend(result['events'])
            if k_task.done():await k_task
            if seq%800==0: print('Paced saved audio:',round(seq*.032),'seconds',flush=True)
        finals=[e for e in report['events'] if e['type']=='recognition' and e['final']]
        report.update(finals=len(finals),max_feed_ms=maximum,
            max_job_age_ms=max(e['job_age_ms'] for e in finals),
            max_queue_wait_ms=max(e['queue_wait_ms'] for e in finals),
            fault=engine.fault,profiles=decoder.profiles)
        assert not engine.fault and len(finals)==5
        assert report['max_job_age_ms']<=2500
        report['script_agreements']=[score(s['prompt'],e['text'])['exact_words']
            for s,e in zip(recording['guided_test']['steps'],finals)]
        assert all(report['script_agreements'])
        # Stop/mute while a real final is executing, then restart and prove that
        # the old lease cannot publish a transcript into the replacement lease.
        lease_before=lease
        clip=next(c for c in json.loads(Path('.tavi/asr-mlx-comparison/corpus-v1/manifest.json').read_text())['clips']
                  if c['id']=='conversation-bec1b5eb-1')
        with wave.open(clip['windows'][0]['wav']) as w:request=w.readframes(w.getnframes())
        engine.stop(lease)
        lease=(await asyncio.to_thread(engine.start,'hinted'))['stream_id']
        seq=0;began=time.monotonic()
        for offset in range(0,len(request)+32000,1024):
            await asyncio.sleep(max(0,began+seq*.032-time.monotonic()))
            engine.feed(lease,seq,request[offset:offset+1024].ljust(1024,b'\0'));seq+=1
            if engine.running and engine.running.final and decoder.final_backend.active and decoder.final_backend.inflight:break
        assert engine.running and engine.running.final
        cancelled_child=decoder.final_backend.process
        cancelled_lease=lease
        before=time.monotonic();engine.stop(lease)
        report['mute_call_ms']=(time.monotonic()-before)*1000
        async with asyncio.timeout(2):
            while engine.running is not None:await asyncio.sleep(.005)
        lease=(await asyncio.to_thread(engine.start,'hinted'))['stream_id']
        result=engine.feed(lease,0,bytes(1024))
        report['mute_cancelled_native_final']=(cancelled_child.poll() is not None
            and decoder.final_backend.process is not None and decoder.final_backend.process is not cancelled_child)
        report['new_lease_has_no_late_events']=not result['events'] and lease not in (lease_before,cancelled_lease)
        assert report['new_lease_has_no_late_events']
        assert report['mute_cancelled_native_final']
        report['final_budget_usd']=used_budget()
        assert report['final_budget_usd']==report['initial_budget_usd']
        report['completed']=True
    finally:
        stop.set()
        if k_task:
            k_task.cancel();await asyncio.gather(k_task,return_exceptions=True)
        await asyncio.to_thread(engine.close)
        await schedule.close()
        report['schedule']=dict(schedule.metrics)
        (folder/'stream.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('events','scope','profiles')},indent=2),flush=True)


if __name__=='__main__':asyncio.run(run())
