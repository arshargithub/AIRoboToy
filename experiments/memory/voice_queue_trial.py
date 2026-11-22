"""Local K delivery comparison. No microphone, playback or network inference."""
import asyncio
import hashlib
import json
import statistics
import time
from experiments.memory.runtime import ROOT, SSD, require_ssd
from experiments.memory.decision_contract_v2 import validate, snapshot
from experiments.memory.voice_queue import chunks
from tavi.local_speech import LocalSpeech
from tavi.experiment_workflow import begin, audit, finish


async def run():
    require_ssd()
    folder, plan = begin(ROOT/'experiments/memory/voice-queue-protocol.json', run_root=SSD/'runs/scored')
    print(json.dumps({'run': str(folder), 'audit': audit(folder)}), flush=True)
    data = json.loads((ROOT/'experiments/memory/voice-queue-input.json').read_text())
    result = {'blocked': [], 'pairs': [], 'errors': []}
    voice = LocalSpeech('kokoro-k-mlx')
    path = folder/'observations.json'
    def save(): path.write_text(json.dumps(result, indent=2)+'\n')
    async def work():
        eligible = []
        for row in data['rows']:
            bound = snapshot(row['task'], row['memory_evidence'])
            try:
                validate(row['value'], row['task'], row['memory_evidence'],
                         issued_snapshot=row['request_snapshot'], current_snapshot=bound)
            except ValueError as exc:
                result['blocked'].append({'id': row['case_id'], 'reason': str(exc)}); continue
            eligible.append(row)
        start = time.monotonic(); await voice.prepare()
        result['worker_prepare_ms'] = (time.monotonic()-start)*1000
        for repeat in range(plan['configuration']['repeats']):
            for index, row in enumerate(eligible):
                pair = {'case_id': row['case_id'], 'repeat': repeat, 'text': row['text'],
                        'historical_context_reply_ms': row['pipeline_ms']}
                for arm in (['whole','sentences'] if (index+repeat)%2==0 else ['sentences','whole']):
                    start = time.monotonic()
                    if arm == 'whole':
                        audio = await voice.synthesize(row['text'])
                        pair[arm] = {'first_audio_ms': (time.monotonic()-start)*1000,
                                     'duration_ms': audio.duration_ms,
                                     'audio_sha256': hashlib.sha256(audio.wav).hexdigest()}
                    else:
                        pieces = []
                        async for chunk in chunks(voice, row['value'], row['task'], row['memory_evidence'],
                                issued_snapshot=row['request_snapshot'], current_snapshot=row['request_snapshot']):
                            audio = chunk.pop('audio')
                            chunk.update(ready_ms=(time.monotonic()-start)*1000,
                                         duration_ms=audio.duration_ms,
                                         audio_sha256=hashlib.sha256(audio.wav).hexdigest())
                            pieces.append(chunk)
                        clock = pieces[0]['ready_ms'] + 250
                        gaps = []
                        for piece in pieces:
                            available = piece['ready_ms'] + 250
                            gaps.append(max(0, available-clock))
                            clock = max(clock, available)+piece['duration_ms']
                        pair[arm] = {'first_audio_ms': pieces[0]['ready_ms'],
                                     'all_audio_ms': pieces[-1]['ready_ms'], 'chunks': pieces,
                                     'predicted_gap_ms': sum(gaps)}
                pair['first_audio_saving_ms'] = pair['whole']['first_audio_ms']-pair['sentences']['first_audio_ms']
                pair['work_ratio'] = pair['sentences']['all_audio_ms']/pair['whole']['first_audio_ms']
                result['pairs'].append(pair); save()
                print(json.dumps({'case': row['case_id'], 'repeat': repeat,
                                  'saving_ms': round(pair['first_audio_saving_ms'])}), flush=True)
    try:
        await asyncio.wait_for(work(), plan['limits']['maximum_wall_seconds'])
    except Exception as exc:
        result['errors'].append(type(exc).__name__+': '+str(exc))
    finally:
        await voice.close(); save()
    pairs = result['pairs']
    metrics = {'blocked_before_synthesis': len(result['blocked']), 'paired_samples': len(pairs),
               'text_reconstruction_errors': sum(''.join(c['text'] for c in p['sentences']['chunks']) != p['text'] for p in pairs),
               'synthesis_errors': len(result['errors']),
               'predicted_underrun_samples': sum(p['sentences']['predicted_gap_ms'] > 0 for p in pairs),
               'median_first_audio_saving_ms': statistics.median(p['first_audio_saving_ms'] for p in pairs) if pairs else None,
               'median_synthesis_work_ratio': statistics.median(p['work_ratio'] for p in pairs) if pairs else None,
               'additional_api_usd': 0.0}
    record = finish(folder, metrics, artifacts=[path], completed=not result['errors'],
                    error='; '.join(result['errors']) or None)
    print(json.dumps({'run': str(folder), 'metrics': metrics, 'decision': record['decision']['outcome'], 'audit': audit(folder)}), flush=True)


if __name__ == '__main__': asyncio.run(run())
