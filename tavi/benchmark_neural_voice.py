"""Offline callback timing, continuity model and cancellation for neural TTS."""
import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import statistics
import time

from .benchmark_conversation_voice import CASES
from .neural_voice import create_engine, generate, pcm_wave

CRITERIA = {'median_first_chunk_ms': 1000, 'maximum_first_chunk_ms': 1500,
            'maximum_rtf': .6, 'initial_playback_buffer_ms': 250,
            'maximum_cancel_return_ms': 250, 'repeats': 3}


def run(model, folder, repeats=3):
    import numpy as np
    folder.mkdir(parents=True, exist_ok=False)
    start = time.perf_counter(); engine, config = create_engine(model)
    load_ms = (time.perf_counter()-start)*1000
    report = {'schema_version': 1, 'model': model, 'api_spend_usd': 0,
              'scope': 'Fixed synthetic text; no microphone, cloud or playback',
              'sherpa_version': importlib.metadata.version('sherpa-onnx'),
              'piper_version': importlib.metadata.version('piper-tts') if model == 'piper' else None,
              'threads': 2, 'criteria': CRITERIA, 'load_and_verification_ms': load_ms,
              'silence_scale': 1 if model == 'pocket' else None,
              'trials': [], 'limitations': ['First chunk is PCM readiness, not audible first speech.',
                  'Continuity is modeled with 250 ms initial buffering, not actual transport/playback.',
                  'Same fixed text suite as previous Mac benchmark; no independent listening-quality assessment.',
                  'Cancellation requested at callback boundary, not arbitrary acoustic onset.']}

    def trial(key, text, repeat):
        chunks = []; trace = []; started = time.perf_counter()
        def callback(samples, progress):
            trace.append({'at_ms': (time.perf_counter()-started)*1000, 'samples': len(samples)})
            chunks.append(np.array(samples, dtype='float32', copy=True))
            return 1
        audio = generate(engine, config, text, callback)
        elapsed = (time.perf_counter()-started)*1000
        assert chunks and sum(len(x) for x in chunks) == len(audio.samples)
        assert np.allclose(np.concatenate(chunks), np.asarray(audio.samples))
        name = f'{key}-{repeat}.wav'; (folder/name).write_bytes(pcm_wave(audio.samples, audio.sample_rate))
        clock = trace[0]['at_ms']+CRITERIA['initial_playback_buffer_ms']; gap = 0
        for event in trace:
            gap += max(0, event['at_ms']-clock)
            clock = max(clock, event['at_ms'])+event['samples']*1000/audio.sample_rate
        return {'case': key, 'repeat': repeat, 'text': text, 'wav': name,
                'first_chunk_ms': trace[0]['at_ms'], 'complete_ms': elapsed,
                'audio_duration_ms': len(audio.samples)*1000/audio.sample_rate,
                'rtf': elapsed/(len(audio.samples)*1000/audio.sample_rate),
                'modeled_gap_ms': gap, 'callbacks': trace}

    report['warmup'] = trial('warmup', 'The little dragon found a golden key.', 0)
    for repeat in range(repeats):
        for key, parts in CASES[repeat:]+CASES[:repeat]:
            row = trial(key, ''.join(parts), repeat+1)
            report['trials'].append(row)
            (folder/'report.json').write_text(json.dumps(report, indent=2)+'\n')
            print(f'{model} {key} {repeat+1}/{repeats}: first {row["first_chunk_ms"]:.0f} ms; complete {row["complete_ms"]:.0f} ms; RTF {row["rtf"]:.2f}; modeled gap {row["modeled_gap_ms"]:.0f} ms', flush=True)
    cancelled = []
    for _ in range(3):
        requested = []
        def cancel(samples, progress):
            requested.append(time.perf_counter()); return 0
        started = time.perf_counter()
        generate(engine, config, ''.join(CASES[-1][1]), cancel)
        ended = time.perf_counter()
        assert len(requested) == 1
        cancelled.append({'first_callback_ms': (requested[0]-started)*1000,
                          'return_after_cancel_ms': (ended-requested[0])*1000})
    report['cancellations'] = cancelled
    report['after_cancel'] = trial('after_cancel', 'The little dragon found a golden key.', 0)
    rows = report['trials']; first = [r['first_chunk_ms'] for r in rows]
    summary = {'trials': len(rows), 'median_first_chunk_ms': statistics.median(first),
               'maximum_first_chunk_ms': max(first),
               'median_complete_ms': statistics.median(r['complete_ms'] for r in rows),
               'maximum_rtf': max(r['rtf'] for r in rows),
               'modeled_gap_trials': sum(r['modeled_gap_ms']>0 for r in rows),
               'maximum_cancel_return_ms': max(r['return_after_cancel_ms'] for r in cancelled)}
    summary['timing_candidate'] = (repeats >= CRITERIA['repeats']
        and summary['median_first_chunk_ms'] <= CRITERIA['median_first_chunk_ms']
        and summary['maximum_first_chunk_ms'] <= CRITERIA['maximum_first_chunk_ms']
        and summary['maximum_rtf'] <= CRITERIA['maximum_rtf']
        and summary['modeled_gap_trials'] == 0
        and summary['maximum_cancel_return_ms'] <= CRITERIA['maximum_cancel_return_ms'])
    report['summary'] = summary
    (folder/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model', choices=['pocket', 'kokoro', 'piper'], default='pocket')
    p.add_argument('--repeats', type=int, choices=range(1, 4), default=3)
    args = p.parse_args()
    folder = Path('.tavi/neural-voice-benchmark')/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    report = run(args.model, folder, args.repeats)
    print(json.dumps({'report': str(folder/'report.json'), 'summary': report['summary']}, indent=2))


if __name__ == '__main__': main()
