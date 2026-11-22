"""Actual unchanged K and turbo ASR in memory; no microphone or playback.

Two authored synthetic clips are readiness/contention controls, never human
recognition or acoustic/wake acceptance. Existing3s final-ASR bound retained.
"""
import asyncio
import hashlib
from io import BytesIO
import re
import time
import wave

from tavi.local_speech import LocalSpeech
from tavi.inference_schedule import ScheduledSpeech
from tavi.mlx_final_asr import MlxFinalASR

PHRASES=['Paprika, could we build a cardboard boat?','Wait, make it a paper rocket instead.']


def pcm16k(data):
    import audioop
    with wave.open(BytesIO(data)) as w:
        if (w.getframerate(),w.getnchannels(),w.getsampwidth())!=(24000,1,2):raise ValueError('Pinned K format changed')
        raw=w.readframes(w.getnframes())
    return audioop.ratecv(raw,2,1,24000,16000,None)[0]


async def run():
    voice=LocalSpeech('kokoro-k-mlx');schedule=ScheduledSpeech(voice,asyncio.get_running_loop());asr=MlxFinalASR(schedule)
    result={'actual_K':True,'actual_turbo':True,'physical_audio':False,'clips':[]};kp=ap=None;warm=None
    try:
        start=time.monotonic();await asyncio.to_thread(asr.prepare);result['asr_prepare_ms']=(time.monotonic()-start)*1000
        start=time.monotonic();await schedule.prepare();result['K_prepare_ms']=(time.monotonic()-start)*1000
        clips=[]
        for phrase in PHRASES:
            s=await schedule.synthesize(phrase);clips.append(s.wav)
        for i,(phrase,clip) in enumerate(zip(PHRASES,clips)):
            if i==1:
                warm=asyncio.create_task(schedule.synthesize('A tiny cardboard boat is ready for a bright paper flag. A little rocket can join our pretend adventure across the stars.'))
                async with asyncio.timeout(4):
                    while not voice.inflight and not warm.done():await asyncio.sleep(.001)
            pcm=pcm16k(clip);start=time.monotonic()
            decoded=await asyncio.to_thread(asr.decode,pcm,time.monotonic()+3)
            text=decoded.text;words=re.findall(r'[a-z]+',text.lower());expected=('cardboard','boat') if i==0 else ('paper','rocket')
            result['clips'].append({'phrase':phrase,'text':text,'wav_sha256':hashlib.sha256(clip).hexdigest(),'input_seconds':len(pcm)/32000,
                                    'decode_ms':(time.monotonic()-start)*1000,'intent_present':all(w in words for w in expected),'confidence':decoded.confidence})
            if warm:await warm;warm=None
        result['scheduler']=dict(schedule.metrics);result['holds_released']=not schedule.holds
        kp=voice.process;ap=asr.process
    finally:
        if warm:warm.cancel();await asyncio.gather(warm,return_exceptions=True)
        await schedule.close();await asyncio.to_thread(asr.close)
        result['workers_closed']=voice.process is None and asr.process is None and (kp is None or kp.returncode is not None) and (ap is None or ap.poll() is not None)
    return result
