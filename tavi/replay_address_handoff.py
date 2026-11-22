"""Local single-turn wake/request handoff replay; never opens a microphone.

Real saved PCM, Silero, tiny/base and K. The reasoning provider is a local stub
and playback ACKs are accelerated. No API request, speaker output or new audio
capture. This diagnoses a known development case, not household acceptance.
"""
import argparse
import asyncio
import json
from pathlib import Path
import time
import wave

from .acoustics import Silero
from .chunked_conversation import ChunkedConversation
from .live_wake import LiveWake, WhisperDecoder
from .local_speech import LocalSpeech, validate_wave
from .storage import Store


async def run(manifest_path, expected_request=None,stop_after_completion=False):
    manifest = json.loads(manifest_path.read_text())
    with wave.open(manifest['runs'][0]['microphone_wav']) as wav:
        if (wav.getframerate(),wav.getnchannels(),wav.getsampwidth())!=(16000,1,2):
            raise ValueError('Expected saved PCM16 mono at 16 kHz')
        pcm = wav.readframes(wav.getnframes())

    class Brain:
        def __init__(self): self.calls=[]
        async def stream_reply(self,history):
            self.calls.append(list(history))
            yield 'We could build a soft castle with three cushions. Add a tall tower and a secret door!'
        async def close(self): pass

    brain=Brain(); voice=LocalSpeech('kokoro-k-mlx'); store=Store()
    conversation=ChunkedConversation(store,provider=brain,speech=voice)
    engine=LiveWake(Silero(Path('.tavi/models/silero_vad.onnx'),wake_backend='off'),WhisperDecoder(final_model='base.en'))
    report={'scope':__doc__, 'source_sha256':manifest['source_sha256'], 'api_spend_usd':0,
            'recognitions':[], 'played_sequences':[], 'completed':False}
    lease=None
    try:
        # Match service startup: prepare the native worker BEFORE opening the
        # capture lease. A cold model startup can exceed the idle lease timeout.
        await voice.prepare()
        lease=engine.start('hinted')['stream_id']; conversation.start(lease)
        started=time.perf_counter()
        for seq,offset in enumerate(range(0,len(pcm)+32000,1024)):
            await asyncio.sleep(max(0,started+seq*.032-time.perf_counter()))
            result=engine.feed(lease,seq,pcm[offset:offset+1024].ljust(1024,b'\0'))
            conversation.feed(lease,result)
            for event in result['events']:
                if event['type']=='recognition':
                    report['recognitions'].append({k:event.get(k) for k in
                        ('text','final','utterance','recognition_id','asr_run_id','decode_ms','address_verification')})
                    print('Final' if event['final'] else 'Partial',repr(event['text']),flush=True)
            if conversation.audio is not None:
                audio=conversation.audio; rid=audio['id']; sequence=audio['sequence']
                validate_wave(conversation.audio_bytes(lease,rid,sequence),24000)
                for command in ('started','played'):
                    assert conversation.command(lease,command,{'response_id':rid,'sequence':sequence})
                report['played_sequences'].append(sequence)
            if conversation.failure: raise AssertionError(conversation.failure)
            if stop_after_completion and conversation.completed_response_id is not None:
                report['stopped_after_completed_reply']=True
                report['replayed_seconds']=(seq+1)*.032
                break
        accepted=[m for m in conversation.metrics if m['kind']=='accepted_turn']
        assert len(accepted)==1 and accepted[0]['address_source']=='partial_prefix'
        assert len(brain.calls)==1
        request=brain.calls[0][-1]['content']
        if expected_request is not None: assert request==expected_request
        assert report['played_sequences']==[0,1]
        assert conversation.completed_response_id is not None and engine.fault is None
        report.update(completed=True,accepted=accepted,request=request,reasoning_stub_calls=len(brain.calls),
                      microphone_recordings=0,fault=engine.fault,metrics=list(conversation.metrics))
        print('Accepted once; completed ordered K audio; no cloud call.',flush=True)
    finally:
        report['metrics']=list(conversation.metrics)
        manifest_path.with_name('address-handoff-replay.json').write_text(json.dumps(report,indent=2)+'\n')
        await conversation.close()
        if lease: engine.stop(lease)
        engine.close();store.close()
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('--expected-request')
    parser.add_argument('--stop-after-completion',action='store_true')
    args=parser.parse_args();asyncio.run(run(args.manifest,args.expected_request,args.stop_after_completion))
