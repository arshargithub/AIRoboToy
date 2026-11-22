"""Paired K whole/sentence synthesis experiment, with no cloud or microphone.

Uses the actual isolated production worker. Explicit sentence boundaries keep
this timing experiment separate from automatic text splitting or deployment.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from .benchmark_conversation_voice import CASES, CRITERIA, summarize
from .local_speech import LocalSpeech


async def run(folder, repeats=3):
    folder.mkdir(parents=True, exist_ok=False)
    voice = LocalSpeech('kokoro-k-mlx')
    report = {
        'schema_version': 1, 'backend': voice.backend,
        'scope': 'Synthetic text; no microphone, network or speaker playback',
        'api_spend_usd': 0, 'criteria': CRITERIA, 'repeats': repeats,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'pairs': [], 'completed': False,
        'limitations': [
            'All text is available at time zero; excludes reasoning and ASR.',
            'Manually specified text boundaries, not a runtime sentence splitter.',
            'First ready is validated WAV receipt, not audible browser playback.',
            'Gaps are modeled using actual durations plus 250 ms handoff allowance.',
            'No listening/prosody or live cancellation acceptance; no runtime promotion.',
            'One Mac under observed load; small development suite, no p95 claim.',
        ],
    }
    def save():
        (folder/'report.json').write_text(json.dumps(report, indent=2)+'\n')

    async def synth(text, name):
        start = time.perf_counter()
        audio = await voice.synthesize(text)
        elapsed = (time.perf_counter()-start)*1000
        (folder/name).write_bytes(audio.wav)
        return {'ready_ms': elapsed, 'duration_ms': audio.duration_ms, 'wav': name}

    try:
        start = time.perf_counter()
        await voice.prepare()
        report['warm_initialization_ms'] = (time.perf_counter()-start)*1000
        for repeat in range(repeats):
            for key, parts in CASES[repeat:]+CASES[:repeat]:
                row = {'case': key, 'repeat': repeat+1, 'chunks': len(parts)}
                order = ['whole', 'split'] if (repeat+CASES.index((key, parts)))%2 == 0 else ['split', 'whole']
                row['order'] = order
                for strategy in order:
                    texts = (''.join(parts),) if strategy == 'whole' else parts
                    outputs = [await synth(text, f'{key}-{repeat+1}-{strategy}-{n}.wav')
                               for n, text in enumerate(texts)]
                    row[strategy] = {'first_ready_ms': outputs[0]['ready_ms'],
                                     'total_work_ms': sum(o['ready_ms'] for o in outputs),
                                     'audio_duration_ms': sum(o['duration_ms'] for o in outputs),
                                     'outputs': outputs}
                first = row['split']['outputs'][0]
                remaining = sum(o['ready_ms'] for o in row['split']['outputs'][1:])
                row['first_audio_saving_ms'] = row['whole']['first_ready_ms']-first['ready_ms']
                row['total_work_ratio'] = row['split']['total_work_ms']/row['whole']['total_work_ms']
                row['predicted_gap_ms'] = max(0, remaining+CRITERIA['handoff_allowance_ms']-first['duration_ms']) if len(parts)>1 else 0
                report['pairs'].append(row)
                save()
                print(f'{key} {repeat+1}: saving {row["first_audio_saving_ms"]:.0f} ms; gap {row["predicted_gap_ms"]:.0f} ms', flush=True)
        report['summary'] = summarize(report['pairs'], repeats)
        report['completed'] = True
        save()
        return report
    finally:
        await voice.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    folder = args.output or Path('.tavi/k-chunk-benchmark')/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    report = asyncio.run(run(folder))
    print(json.dumps({'report': str(folder/'report.json'), 'summary': report['summary']}, indent=2))


if __name__ == '__main__':
    main()
