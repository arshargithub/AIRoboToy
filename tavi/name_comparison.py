"""Frozen, local-only Tavi/Paprika development comparison.

No inference result from this screen qualifies a live wake system. All private
results, including transcripts, are written under ignored .tavi/ only.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import time

os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'

import numpy as np

PROTOCOL_PATH = Path(__file__).with_name('web') / 'name-comparison-protocol.json'


def protocol():
    raw = PROTOCOL_PATH.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def load_collection(path):
    plan, digest = protocol()
    if path.stat().st_size > 12_000_000:
        raise ValueError('Collection exceeds the size bound')
    data = json.loads(path.read_text())
    expected = {'kind': plan['kind'], 'schema_version': 1, 'protocol_id': plan['protocol_id'],
                'protocol_sha256': digest, 'sample_rate': 16000, 'format': 'mono_pcm16le_base64'}
    if any(data.get(k) != v for k, v in expected.items()):
        raise ValueError('Collection does not match the frozen comparison protocol')
    if data.get('complete') is not True or not isinstance(data.get('clips'), list) or len(data['clips']) != len(plan['trials']):
        raise ValueError('A complete 32-clip comparison is required; partial samples are not silently scored')
    clips = []
    for source, trial in zip(data['clips'], plan['trials']):
        if any(source.get(k) != v for k, v in trial.items()):
            raise ValueError('Clip labels or cue order differ from the frozen protocol')
        raw = base64.b64decode(source['pcm_base64'], validate=True)
        count = len(raw) // 2
        if len(raw) % 2 or not plan['minimum_frames'] * 512 <= count <= plan['max_frames'] * 512 or source.get('sample_count') != count:
            raise ValueError('Clip has invalid or incomplete PCM data')
        clips.append({**trial, 'pcm': np.frombuffer(raw, dtype='<i2').copy()})
    return data, clips


def matches(text, names):
    return [name for name in names if re.search(r'\b' + re.escape(name) + r'\b', text, re.IGNORECASE)]


def summarize(rows, names):
    result = {}
    for name in names:
        groups = {}
        for category in ('name_alone', 'request', 'confusable', 'mention', 'other_name'):
            cases = [r for r in rows if (r['target'] == name and r['category'] == category)
                     or (category in ('confusable', 'mention') and r['category'] == category)
                     or (category == 'other_name' and r['target'] is not None and r['target'] != name)]
            groups[category] = {'clips': len(cases), 'name_matches': sum(name in r['matches'] for r in cases)}
        positives = [r for r in rows if r['target'] == name]
        result[name] = {'intended_calls': len(positives),
                        'detected_calls': sum(name in r['matches'] for r in positives), 'groups': groups}
    times = [r['decode_ms'] for r in rows if 'decode_ms' in r]
    return {'names': result, 'ambiguous_both_name_clips': sum(len(r['matches']) > 1 for r in rows),
            'clips_without_vad_speech': sum(r.get('reason') == 'no_speech' for r in rows),
            'median_decode_ms': float(np.median(times)) if times else None}


def verify_model(root, plan):
    for filename, expected in plan['model_files'].items():
        if hashlib.sha256((root / filename).read_bytes()).hexdigest() != expected:
            raise ValueError('Local ASR weights differ from the frozen comparison')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('collection', type=Path)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    data, clips = load_collection(args.collection)
    plan, digest = protocol()
    if args.validate_only:
        print(json.dumps({'valid_complete_collection': True, 'clips': len(clips), 'protocol_sha256': digest}))
        return
    root = Path('.tavi/models/whisper-tiny-en')
    verify_model(root, plan)
    from faster_whisper import WhisperModel
    from .acoustics import Silero
    model = WhisperModel(str(root), device='cpu', compute_type='int8', cpu_threads=2, local_files_only=True)
    vad = Silero(Path('.tavi/models/silero_vad.onnx'), wake_backend='off')
    # Crop each recording identically for every prompt; labels never affect audio.
    cropped = []
    for clip in clips:
        vad.reset()
        pcm, speech = clip['pcm'], []
        for offset in range(0, len(pcm), 512):
            part = pcm[offset:offset + 512]
            part = np.pad(part, (0, 512 - len(part)))
            if vad.probability(part.tobytes()) >= .5:
                speech.append(offset)
        cropped.append(pcm[max(0, speech[0] - 1600):min(len(pcm), speech[-1] + 512 + 3200)].astype(np.float32) / 32768 if speech else None)
    results = []
    for index, prompt in enumerate(plan['prompts']):
        rows = []
        for clip, crop in zip(clips, cropped):
            row = {k: v for k, v in clip.items() if k != 'pcm'}
            if crop is None:
                rows.append({**row, 'matches': [], 'reason': 'no_speech'})
                continue
            started = time.perf_counter()
            segments, _ = model.transcribe(crop, initial_prompt=prompt, **plan['asr'])
            segments = list(segments)
            duration = (time.perf_counter() - started) * 1000
            text = ' '.join(s.text for s in segments).strip()
            rows.append({**row, 'text': text, 'matches': matches(text, plan['names']), 'decode_ms': duration,
                         'audio_seconds': len(crop) / 16000,
                         'segments': [{'avg_logprob': s.avg_logprob, 'no_speech_prob': s.no_speech_prob} for s in segments]})
        result = {'role': 'primary' if index == 0 else 'sensitivity_control', 'prompt': prompt,
                  'summary': summarize(rows, plan['names']), 'cases': rows}
        results.append(result)
        print(json.dumps({k: v for k, v in result.items() if k != 'cases'}), flush=True)
    report = {'scope': 'Fresh matched-name development screen; not household or family acceptance',
              'protocol_id': plan['protocol_id'], 'protocol_sha256': digest,
              'source_sha256': hashlib.sha256(args.collection.read_bytes()).hexdigest(),
              'model_files': plan['model_files'], 'speaker': data.get('speaker'),
              'attempts': data.get('attempts', {}), 'capture_segments': data.get('capture_segments', []),
              'fixture_only': data.get('fixture_only', False),
              'results': results, 'api_spend_usd': 0}
    out = Path('.tavi/private-wake-analysis')
    out.mkdir(parents=True, exist_ok=True)
    # Content addressing prevents overwriting a different speaker/session.
    (out / ('name-comparison-' + report['source_sha256'][:16] + '.json')).write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
