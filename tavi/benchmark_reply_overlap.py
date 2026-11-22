"""Synthetic text-stream/K overlap pilot; no microphone or speaker playback.

18 streamed requests and six non-streamed controls, at most $1.20 reserved in
the existing $25 ledger. Paired voice comparisons use the SAME completed text.
No provisional audio is sent to a browser or selected in the live controller.
"""
import argparse
import asyncio
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import statistics
import time
import wave

from .conversation_providers import PaidText, MODEL, REQUEST_RESERVATION
from .local_speech import LocalSpeech, validate_wave
from .sentence_chunks import SentenceChunks
from .storage import Store

PROMPTS = (
    ('craft', 'Paprika, what can we make with a cardboard box?'),
    ('followup', 'How could we make a cardboard spaceship?'),
    ('story', 'Tell me a short story about a fox finding a secret door.'),
    ('replacement', 'Make it an underwater adventure with a turtle instead.'),
    ('explanation', 'Why does the moon look different on different nights?'),
    ('game', 'Invent a little animal guessing game we can play together.'),
)
CRITERIA = {
    'minimum_median_saving_ms': 500,
    'minimum_fraction_saving_500ms': .75,
    'handoff_allowance_ms': 250,
    'maximum_work_ratio': 1.75,
    'minimum_repeats': 3,
    'guarded_whole_wav_minimum_median_saving_ms': 300,
}


def combine(pieces):
    output = BytesIO()
    with wave.open(output, 'wb') as target:
        target.setnchannels(1); target.setsampwidth(2); target.setframerate(24000)
        for piece in pieces:
            with wave.open(BytesIO(piece.wav)) as source:
                target.writeframes(source.readframes(source.getnframes()))
    return validate_wave(output.getvalue(), 24000)


async def overlap(provider, voice, history):
    """Measure bounded concurrent stages; no endpoint publication occurs."""
    queue = asyncio.Queue(maxsize=4)
    splitter = SentenceChunks()
    result = {'chunks': [], 'deltas': [], 'text': ''}
    pieces = []
    start = time.perf_counter()
    now = lambda: (time.perf_counter()-start)*1000

    async def produce():
        async for delta in provider.stream_reply(history):
            result['text'] += delta
            result['deltas'].append({'at_ms': now(), 'characters': len(delta)})
            for text in splitter.feed(delta): await queue.put(text)
        result['text_completed_ms'] = now()
        for text in splitter.finish(): await queue.put(text)
        await queue.put(None)

    async def consume():
        while (text := await queue.get()) is not None:
            began = now()
            audio = await voice.synthesize(text)
            pieces.append(audio)
            result['chunks'].append({'text': text, 'start_ms': began, 'ready_ms': now(),
                                     'duration_ms': audio.duration_ms})

    async with asyncio.TaskGroup() as tasks:
        tasks.create_task(produce()); tasks.create_task(consume())
    if ''.join(c['text'] for c in result['chunks']) != result['text']:
        raise ValueError('Missing or repeated streamed text')
    audio = combine(pieces)
    result['guarded_whole_wav_ms'] = now()
    result['first_speculative_audio_ms'] = result['chunks'][0]['ready_ms']
    # Actual readiness trace plus a conservative allowance at EVERY handoff.
    clock = result['chunks'][0]['ready_ms']
    gaps = []
    for n, chunk in enumerate(result['chunks']):
        available = chunk['ready_ms'] + (CRITERIA['handoff_allowance_ms'] if n else 0)
        gaps.append(max(0, available-clock))
        clock = max(clock, available)+chunk['duration_ms']
    result['predicted_gap_ms'] = sum(gaps)
    result['duration_ms'] = audio.duration_ms
    return result, audio


async def run(folder, data_dir=Path('.tavi/simulation')):
    ledger = data_dir/'simulation.sqlite3'
    if not ledger.is_file():
        raise FileNotFoundError('Use the existing service data directory; do not create a separate experiment ledger')
    folder.mkdir(parents=True, exist_ok=False)
    store = Store(ledger)
    initial = store.used_micro_usd()
    experiment_ceiling = initial+24*REQUEST_RESERVATION
    provider, voice = PaidText(store), LocalSpeech('kokoro-k-mlx')
    report = {
        'schema_version': 1, 'model': MODEL, 'voice': voice.backend,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'scope': 'Synthetic text only; existing authorized OpenAI text destination; local K audio; no microphone/upload/playback',
        'criteria': CRITERIA, 'initial_spent_reserved_usd': initial/1e6,
        'authoritative_ledger': str(ledger),
        'maximum_additional_reservation_usd': 1.2,
        'pairs': [], 'nonstreamed_controls': [], 'completed': False,
        'limitations': [
            'Readiness is PCM/WAV availability, not browser audible latency.',
            'Paired serial estimates use the observed streamed completion time plus whole synthesis of identical text, not identical independent cloud requests.',
            'Six independent nonstreamed controls are descriptive only; generated wording and service load can differ.',
            'First chunk is speculative until terminal completion; failure can invalidate a prefix.',
            'Guarded mode withholds the entire combined WAV until all text and synthesis succeeds.',
            'Gaps are modeled, without browser transport, ASR/GPU concurrency or listening/prosody acceptance.',
            'Small fixed development suite on one Mac; no p95 or product acceptance.',
        ],
    }
    def save():
        report['final_spent_reserved_usd'] = store.used_micro_usd()/1e6
        (folder/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    def budget_check():
        if store.used_micro_usd()+REQUEST_RESERVATION > experiment_ceiling:
            raise ValueError('Experiment reservation envelope exhausted')
    async def serial(text):
        start = time.perf_counter(); audio = await voice.synthesize(text)
        return (time.perf_counter()-start)*1000, audio
    try:
        await voice.prepare()
        for repeat in range(3):
            for key, prompt in PROMPTS[repeat:]+PROMPTS[:repeat]:
                history = [{'role':'user', 'content':prompt}]
                budget_check()
                row, audio = await overlap(provider, voice, history)
                row.update(case=key, repeat=repeat+1)
                whole_ms, whole = await serial(row['text'])
                row['whole_synthesis_ms'] = whole_ms
                row['serial_counterfactual_ms'] = row['text_completed_ms']+whole_ms
                row['speculative_saving_ms'] = row['serial_counterfactual_ms']-row['first_speculative_audio_ms']
                row['guarded_saving_ms'] = row['serial_counterfactual_ms']-row['guarded_whole_wav_ms']
                row['work_ratio'] = sum(c['ready_ms']-c['start_ms'] for c in row['chunks'])/whole_ms
                row['whole_duration_ms'] = whole.duration_ms
                (folder/f'{key}-{repeat+1}-overlap.wav').write_bytes(audio.wav)
                (folder/f'{key}-{repeat+1}-whole.wav').write_bytes(whole.wav)
                report['pairs'].append(row); save()
                print(f'{key} {repeat+1}: text {row["text_completed_ms"]:.0f} ms; speculative {row["first_speculative_audio_ms"]:.0f}; guarded {row["guarded_whole_wav_ms"]:.0f}; guarded saving {row["guarded_saving_ms"]:.0f}; gap {row["predicted_gap_ms"]:.0f}', flush=True)
                if repeat == 0:
                    budget_check(); start = time.perf_counter()
                    text = await provider.reply(history)
                    text_ms = (time.perf_counter()-start)*1000
                    synth_ms, _ = await serial(text)
                    report['nonstreamed_controls'].append({'case':key, 'text_ms':text_ms, 'synthesis_ms':synth_ms, 'total_ms':text_ms+synth_ms})
                    save()
        rows = report['pairs']
        speculative = [r['speculative_saving_ms'] for r in rows]
        guarded = [r['guarded_saving_ms'] for r in rows]
        summary = {
            'pairs': len(rows),
            'median_speculative_saving_ms': statistics.median(speculative),
            'fraction_speculative_saving_500ms': sum(s>=500 for s in speculative)/len(rows),
            'median_guarded_saving_ms': statistics.median(guarded),
            'minimum_guarded_saving_ms': min(guarded),
            'maximum_work_ratio': max(r['work_ratio'] for r in rows),
            'modeled_gap_pairs': sum(r['predicted_gap_ms']>0 for r in rows),
            'median_speculative_ready_ms': statistics.median(r['first_speculative_audio_ms'] for r in rows),
            'median_guarded_ready_ms': statistics.median(r['guarded_whole_wav_ms'] for r in rows),
            'median_serial_counterfactual_ms': statistics.median(r['serial_counterfactual_ms'] for r in rows),
            'median_nonstreamed_control_ms': statistics.median(r['total_ms'] for r in report['nonstreamed_controls']),
            'runtime_promoted': False,
        }
        summary['streaming_timing_candidate'] = (summary['median_speculative_saving_ms']>=500
            and summary['fraction_speculative_saving_500ms']>=.75
            and not summary['modeled_gap_pairs'] and summary['maximum_work_ratio']<=1.75)
        summary['guarded_timing_candidate'] = summary['median_guarded_saving_ms']>=300 and summary['maximum_work_ratio']<=1.75
        report['summary'] = summary; report['completed'] = True; save()
        return report
    finally:
        save()
        await voice.close(); await provider.close(); store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--data-dir', type=Path, default=Path('.tavi/simulation'))
    args = parser.parse_args()
    folder = args.output or Path('.tavi/reply-overlap-benchmark')/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    result = asyncio.run(run(folder, args.data_dir))
    print(json.dumps({'report': str(folder/'report.json'), 'summary': result['summary']}, indent=2))


if __name__ == '__main__': main()
