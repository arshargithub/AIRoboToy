"""Offline synthetic-text Mac voice benchmark; no microphone, cloud or playback.

Compare the existing whole-reply path with one first-sentence chunk followed by
the remainder. Chunks are specified explicitly: this does not validate a runtime
sentence splitter or implement streaming/cancellation. All text is available at
time zero, matching the current non-streaming text provider.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import statistics
import time

from .conversation_providers import MacSpeech


CASES = (
    ('one_sentence', ('Let us build a little rocket and fly to the moon.',)),
    ('brief_answer', ('Yes, we can play a game. ', 'Imagine an animal, and I will ask three questions to guess it.')),
    ('short_story', ('A tiny fox found a silver key. ', 'It opened a door inside an old oak tree, where a sleepy owl was baking star-shaped cookies.')),
    ('three_sentences', ('The little boat sailed past the lighthouse. ', 'A friendly whale showed the captain a secret island. They found a garden where every flower rang like a bell.')),
    ('long_first_sentence', ('Beyond the snowy mountain, a brave little dragon followed a trail of golden feathers through the forest until he reached a quiet lake. ', 'A swan was waiting with a map to the stars.')),
    ('short_first_sentence', ('Ready? ', 'A curious robot packed a sandwich, a flashlight, and a bright red scarf before climbing into a tiny submarine to explore the glowing caves beneath the ocean. There it met a turtle who collected lost bells.')),
)

# Frozen pilot gates, not production acceptance thresholds. A positive timing
# result still requires cancellation, continuity and listening validation.
CRITERIA = {
    'minimum_median_first_audio_saving_ms': 500,
    'minimum_fraction_multichunk_pairs_meeting_saving': .75,
    'handoff_allowance_ms': 250,
    'maximum_total_synthesis_work_ratio': 1.75,
    'minimum_repeats_for_timing_decision': 3,
}


class MeasuredVoice(MacSpeech):
    def __init__(self):
        self.commands = []

    async def _run(self, *args, text=None):
        start = time.perf_counter()
        await super()._run(*args, text=text)
        self.commands.append({'command': Path(args[0]).name,
                              'elapsed_ms': (time.perf_counter()-start)*1000})


async def prepare(voice, text, path):
    voice.commands = []
    start = time.perf_counter()
    speech = await voice.synthesize(text, cache=False)
    elapsed = (time.perf_counter()-start)*1000
    # Artifact I/O is outside preparation timing; no audio is played.
    path.write_bytes(speech.wav)
    return {'ready_ms': elapsed, 'duration_ms': speech.duration_ms,
            'commands': list(voice.commands), 'wav': path.name}


def summarize(pairs, repeats):
    eligible = [p for p in pairs if p['chunks'] > 1]
    savings = [p['first_audio_saving_ms'] for p in eligible]
    ratios = [p['total_work_ratio'] for p in eligible]
    enough = repeats >= CRITERIA['minimum_repeats_for_timing_decision']
    fraction = sum(s >= CRITERIA['minimum_median_first_audio_saving_ms'] for s in savings)/len(savings)
    timing = (statistics.median(savings) >= CRITERIA['minimum_median_first_audio_saving_ms']
              and fraction >= CRITERIA['minimum_fraction_multichunk_pairs_meeting_saving'])
    continuity = all(p['predicted_gap_ms'] == 0 for p in eligible)
    work = max(ratios) <= CRITERIA['maximum_total_synthesis_work_ratio']
    return {
        'multichunk_pairs': len(eligible),
        'median_first_audio_saving_ms': statistics.median(savings),
        'minimum_first_audio_saving_ms': min(savings),
        'fraction_meeting_saving_target': fraction,
        'median_whole_ready_ms': statistics.median(p['whole']['first_ready_ms'] for p in eligible),
        'median_chunked_first_ready_ms': statistics.median(p['split']['first_ready_ms'] for p in eligible),
        'median_total_work_ratio': statistics.median(ratios),
        'maximum_total_work_ratio': max(ratios),
        'predicted_gap_pairs': sum(p['predicted_gap_ms'] > 0 for p in eligible),
        'maximum_predicted_gap_ms': max(p['predicted_gap_ms'] for p in eligible),
        'enough_repeats': enough, 'timing_gate': timing,
        'modeled_continuity_gate': continuity, 'work_gate': work,
        'timing_candidate': enough and timing and continuity and work,
        'runtime_promoted': False,
    }


async def benchmark(repeats, folder):
    folder.mkdir(parents=True, exist_ok=False)
    voice = MeasuredVoice()
    cold = await prepare(voice, 'This is a local voice preparation check.', folder/'cold.wav')
    report = {
        'schema_version': 1, 'kind': 'paprika_offline_voice_latency',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'scope': 'Synthetic text only; no microphone, network calls or speaker playback',
        'api_spend_usd': 0, 'system': platform.system(), 'os_version': platform.mac_ver()[0],
        'machine': platform.machine(), 'voice': 'Samantha', 'rate': 190,
        'sample_rate': 16000, 'cache': False, 'repeats': repeats,
        'criteria': CRITERIA, 'cold_preparation': cold,
        'cases': [{'id': key, 'parts': list(parts)} for key, parts in CASES], 'pairs': [],
        'limitations': [
            'One Mac under uncontrolled load, a small fixed text suite, no p95 claim.',
            'First-ready is validated WAV preparation time, not measured audible playback.',
            'Gap model assumes first chunk starts immediately and remaining synthesis runs during playback; includes 250 ms handoff allowance.',
            'Chunks are manually specified, not a validated automatic sentence splitter.',
            'No listening/prosody, transport, queued playback, microphone or cancellation validation.',
            'End-to-end response time also includes endpointing, ASR and cloud text generation; these are excluded.',
        ],
    }
    for repeat in range(repeats):
        # Rotate cases each repeat and alternate strategy order within pairs.
        cases = CASES[repeat:]+CASES[:repeat]
        for key, parts in cases:
            result = {'case': key, 'repeat': repeat+1, 'chunks': len(parts)}
            order = ['whole', 'split'] if (repeat+CASES.index((key, parts))) % 2 == 0 else ['split', 'whole']
            result['order'] = order
            for method in order:
                chunks = (''.join(parts),) if method == 'whole' else parts
                outputs = []
                for number, text in enumerate(chunks):
                    outputs.append(await prepare(voice, text, folder/f'{key}-{repeat+1}-{method}-{number+1}.wav'))
                result[method] = {'first_ready_ms': outputs[0]['ready_ms'],
                                  'total_work_ms': sum(o['ready_ms'] for o in outputs),
                                  'audio_duration_ms': sum(o['duration_ms'] for o in outputs),
                                  'outputs': outputs}
            first = result['split']['outputs'][0]
            remainder = sum(o['ready_ms'] for o in result['split']['outputs'][1:])
            result['first_audio_saving_ms'] = result['whole']['first_ready_ms']-first['ready_ms']
            result['total_work_ratio'] = result['split']['total_work_ms']/result['whole']['total_work_ms']
            result['predicted_gap_ms'] = max(0, remainder+CRITERIA['handoff_allowance_ms']-first['duration_ms']) if len(parts)>1 else 0
            report['pairs'].append(result)
            # Preserve all completed pairs if a later native command fails.
            (folder/'report.json').write_text(json.dumps(report, indent=2)+'\n')
            print(f'{key} repeat {repeat+1}/{repeats}: whole {result["whole"]["first_ready_ms"]:.0f} ms; first chunk {first["ready_ms"]:.0f} ms; modeled gap {result["predicted_gap_ms"]:.0f} ms', flush=True)
    report['summary'] = summarize(report['pairs'], repeats)
    (folder/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeats', type=int, choices=range(1, 6), default=3)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    folder = args.output or Path('.tavi/voice-latency-benchmark')/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    report = asyncio.run(benchmark(args.repeats, folder))
    print(json.dumps({'report': str(folder/'report.json'), 'summary': report['summary']}, indent=2))


if __name__ == '__main__':
    main()
