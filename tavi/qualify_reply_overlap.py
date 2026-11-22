"""Local replay/load/cancellation checks for the overlap experiment.

Uses existing explicitly saved PCM only for local ASR; synthetic K replies are
replayed from a completed benchmark. No cloud calls, microphone or playback.
"""
import argparse
import asyncio
import json
from pathlib import Path
import time
import wave

from .acoustics import Silero
from .benchmark_reply_overlap import overlap
from .live_wake import LiveWake, WhisperDecoder
from .local_speech import LocalSpeech


class Replay:
    def __init__(self, row): self.row = row
    async def stream_reply(self, history):
        text = self.row['text']; offset = 0; start = time.perf_counter()
        for delta in self.row['deltas']:
            await asyncio.sleep(max(0, delta['at_ms']/1000-(time.perf_counter()-start)))
            end = offset+delta['characters']
            yield text[offset:end]; offset = end
        await asyncio.sleep(max(0, self.row['text_completed_ms']/1000-(time.perf_counter()-start)))


def asr_replay(manifest_path):
    manifest = json.loads(manifest_path.read_text())
    with wave.open(manifest['runs'][0]['microphone_wav']) as wav:
        pcm = wav.readframes(wav.getnframes())
    engine = LiveWake(Silero(Path('.tavi/models/silero_vad.onnx'), wake_backend='off'),
                      WhisperDecoder(final_model='base.en'))
    start = time.perf_counter(); lease = engine.start('hinted')['stream_id']
    maximum = 0; finals = []
    try:
        for seq, offset in enumerate(range(0, len(pcm)+32000, 1024)):
            time.sleep(max(0, start+seq*.032-time.perf_counter()))
            before = time.perf_counter()
            result = engine.feed(lease, seq, pcm[offset:offset+1024].ljust(1024, b'\0'))
            maximum = max(maximum, (time.perf_counter()-before)*1000)
            for event in result['events']:
                if event['type']=='recognition' and event['final']:
                    # Full private text already exists in the earlier local
                    # report; aggregate timing evidence does not need it here.
                    finals.append({k:event.get(k) for k in ('utterance','decode_ms','queue_wait_ms')})
                    print('Concurrent ASR final', event['utterance'], round(event['decode_ms']), 'ms', flush=True)
        return {'finals':finals, 'max_feed_ms':maximum, 'fault':engine.fault,
                'source_sha256':manifest['source_sha256']}
    finally:
        engine.stop(lease); engine.close()


async def run(benchmark_path, manifest_path, resume_load=False):
    benchmark = json.loads(benchmark_path.read_text())
    voice = LocalSpeech('kokoro-k-mlx')
    report = {'scope':'Local saved-audio ASR with synthetic timed K load; native cancellation; no cloud/microphone/playback',
              'api_spend_usd':0, 'completed':False, 'voice_rows':[],
              'limitations':['No browser audible continuity or listening judgment.',
                             'One saved adult development recording, not held-out family speech.',
                             'Intermittent synthesis scheduled every six seconds; not a thermal/endurance or continuous-load benchmark.']}
    path = benchmark_path.with_name('local-qualification.json')
    if resume_load:
        previous = json.loads(path.read_text())
        if len(previous.get('voice_rows',[]))!=18 or len(previous.get('asr',{}).get('finals',[]))!=5:
            raise ValueError('No matching completed local load evidence to resume')
        report['voice_rows'] = previous['voice_rows']
        report['asr'] = previous['asr']
        report['resumed_load_evidence'] = True
        report['fixture_correction'] = 'Cancellation source now emits trailing sentence whitespace before holding the stream; earlier fixture never submitted the second chunk.'
    def save(): path.write_text(json.dumps(report, indent=2)+'\n')
    try:
        await voice.prepare()
        async def load():
            start = time.perf_counter()
            for n, row in enumerate(benchmark['pairs']):
                await asyncio.sleep(max(0, start+n*6-time.perf_counter()))
                trace, _ = await overlap(Replay(row), voice, [])
                report['voice_rows'].append({k:trace[k] for k in ('guarded_whole_wav_ms','first_speculative_audio_ms','predicted_gap_ms')})
                save()
                if (n+1)%3==0: print('Replayed K replies', n+1, flush=True)
        if not resume_load:
            asr, _ = await asyncio.gather(asyncio.to_thread(asr_replay, manifest_path), load())
            report['asr'] = asr; save()
        # Cancel while the second chunk is running in native code. The wrapper
        # only signals entry; the actual production worker owns cancellation.
        entered = asyncio.Event(); calls = []; ended = []
        class Source:
            async def stream_reply(self, history):
                try:
                    yield 'A little fox found a bright silver key. '
                    yield 'Beyond the snowy mountain, a brave little dragon followed a trail of golden feathers through the forest until he reached a quiet lake. '
                    await asyncio.Event().wait()
                finally: ended.append(True)
        class Observed:
            async def synthesize(self, text):
                calls.append(text)
                if len(calls)==2: entered.set()
                return await voice.synthesize(text)
        pending = asyncio.create_task(overlap(Source(), Observed(), []))
        await asyncio.wait_for(entered.wait(), 10)
        old = voice.process
        await asyncio.sleep(.12); start = time.perf_counter(); pending.cancel()
        try: await pending
        except asyncio.CancelledError: pass
        report['cancel'] = {'return_ms':(time.perf_counter()-start)*1000,
                            'native_process_killed':old.returncode is not None and voice.process is None,
                            'text_source_closed':ended==[True], 'no_completed_audio_returned':pending.cancelled()}
        start = time.perf_counter(); fresh = await voice.synthesize('A fresh little rocket is ready.')
        report['cancel']['recovery_first_wav_ms'] = (time.perf_counter()-start)*1000
        report['cancel']['fresh_worker_recovered'] = voice.process.pid != old.pid and fresh.duration_ms>0
        report['completed'] = True; save()
        print(json.dumps({'asr':report['asr'], 'cancel':report['cancel']}, indent=2))
    finally:
        save(); await voice.close()


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('benchmark',type=Path); parser.add_argument('manifest',type=Path)
    parser.add_argument('--resume-load',action='store_true')
    args = parser.parse_args(); asyncio.run(run(args.benchmark,args.manifest,args.resume_load))
