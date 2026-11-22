"""Local, paired capture/ASR experiment. Never uploads clips or changes defaults."""
import argparse
import base64
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import time
from .asr_confidence import finite, segment_confidence

os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
PROTOCOL = Path(__file__).with_name('web') / 'speech-check-protocol.json'
RATE, FRAME = 16000, 512


def load_collection(path):
    plan_bytes = PROTOCOL.read_bytes()
    plan = json.loads(plan_bytes)
    if path.stat().st_size > 4_000_000:
        raise ValueError('Recording exceeds the eight-clip size bound')
    data = json.loads(path.read_text())
    expected = dict(schema_version=1, kind=plan['kind'], protocol_id=plan['protocol_id'],
                    protocol_sha256=hashlib.sha256(plan_bytes).hexdigest(), sample_rate=RATE,
                    format='mono_pcm16le_base64')
    if any(data.get(k) != v for k, v in expected.items()):
        raise ValueError('Recording does not match the frozen speech-check protocol')
    clips = data.get('clips')
    if not isinstance(clips, list) or not 1 <= len(clips) <= 8 or type(data.get('complete')) is not bool:
        raise ValueError('Invalid clip count or completion flag')
    if data['complete'] and len(clips) != 8:
        raise ValueError('A complete recording requires all eight clips')
    result = []
    for clip, trial in zip(clips, plan['trials']):
        if any(clip.get(k) != v for k, v in trial.items()):
            raise ValueError('Clip order or labels differ from the fixed protocol')
        raw = base64.b64decode(clip.get('pcm_base64', ''), validate=True)
        if len(raw) != plan['clip_frames'] * FRAME * 2 or clip.get('sample_count') != len(raw)//2:
            raise ValueError('Clip must contain exactly eight seconds of contiguous PCM16')
        start, cue = clip.get('capture_start_frame'), clip.get('cue_context_frame')
        if type(start) is not int or start < 0 or type(cue) is not int or cue-start != plan['cue_frame']*FRAME:
            raise ValueError('Invalid capture/cue frame metadata')
        result.append({**trial, 'pcm': raw})
    return plan, data, result


def crop_windows(probabilities, sample_count):
    """Reconstruct live final windows, retaining every VAD segment and its bounds.

    full_clip is a boundary control, not a proposed production segmentation rule.
    This does not simulate ASR worker contention, engagement or endpoint barge-in.
    """
    segments, high, active = [], 0, None
    for seq, probability in enumerate(probabilities):
        end = (seq+1)*FRAME
        high = high+1 if probability >= .5 else 0
        if active is None and high >= 2:
            active = {'onset': (seq-1)*FRAME, 'last': end}
        if active is not None:
            if probability >= .5:
                active['last'] = end
            if end-active['last'] >= 12800:
                segments.append({**active, 'endpoint_complete': True})
                active = None
    if active is not None:
        segments.append({**active, 'endpoint_complete': False})
    windows = {'current_100ms': [], 'longer_1000ms': [],
               'full_clip': [{'start': 0, 'stop': sample_count, 'endpoint_complete': None}]}
    for segment in segments:
        for name, pre in [('current_100ms', 1600), ('longer_1000ms', 16000)]:
            windows[name].append({'start': max(0, segment['onset']-pre),
                                  'stop': min(sample_count, segment['last']+3200), **segment})
    return windows


def words(text):
    return re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text.lower())


def score(expected, actual):
    reference, heard = words(expected), words(actual)
    row = list(range(len(heard)+1))
    for i, word in enumerate(reference, 1):
        following = [i]
        for j, other in enumerate(heard, 1):
            following.append(min(following[-1]+1, row[j]+1, row[j-1]+(word != other)))
        row = following
    return {'exact_words': reference == heard, 'word_edits': row[-1],
            'reference_words': len(reference), 'wer': row[-1]/len(reference) if reference else None,
            'first_three_words': heard[:3] == reference[:3] if reference else None,
            'last_three_words': heard[-3:] == reference[-3:] if reference else None,
            'silence_invented_words': bool(heard) if not reference else None}


def calibration_row(row, source_digest, protocol_digest):
    segments = [s for window in row['segment_confidence_by_window'] for s in window['segments']]
    aligned = row['word_alignment_by_window']
    probabilities = [w['probability'] for window in aligned if window['primary_text_agrees']
                     for w in window['words'] if w['probability'] is not None]
    def extremes(key, function):
        values = [s[key] for s in segments if s[key] is not None]
        return function(values) if values else None
    return {'source_sha256': source_digest, 'protocol_sha256': protocol_digest,
            'clip_number': row['number'], 'model': row['model'], 'crop': row['crop'],
            'condition': row['condition'], 'label_source': 'scripted_reference_unverified',
            **{key: row[key] for key in ('category', 'exact_words', 'wer', 'first_three_words',
                                        'last_three_words', 'silence_invented_words', 'decode_ms')},
            'min_avg_logprob': extremes('avg_logprob', min),
            'max_no_speech_prob': extremes('no_speech_prob', max),
            'max_compression_ratio': extremes('compression_ratio', max),
            'min_word_probability': min(probabilities) if probabilities else None,
            'word_alignment_all_agree': all(w['primary_text_agrees'] for w in aligned) if aligned else None,
            'word_alignment_ms': sum(w['alignment_ms'] for w in aligned),
            'vad_segments': len(row['windows'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('collection', type=Path)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    plan, data, clips = load_collection(args.collection)
    if args.validate_only:
        print(json.dumps({'valid': True, 'clips': len(clips), 'complete': data['complete']}))
        return
    import numpy as np
    from .acoustics import Silero
    from faster_whisper import WhisperModel
    # Verify all installed weights before any inference. Never fetch substitutes.
    for model in plan['models'].values():
        for filename, digest in model['files'].items():
            if hashlib.sha256((Path(model['path'])/filename).read_bytes()).hexdigest() != digest:
                raise ValueError('ASR model checksum differs from the frozen protocol')
    vad = Silero(Path('.tavi/models/silero_vad.onnx'), wake_backend='off')
    for clip in clips:
        vad.reset()
        clip['probabilities'] = [vad.probability(clip['pcm'][i:i+1024]) for i in range(0, len(clip['pcm']), 1024)]
        clip['windows'] = crop_windows(clip['probabilities'], len(clip['pcm'])//2)
    rows, warmups = [], {}
    for name, spec in plan['models'].items():
        model = WhisperModel(spec['path'], device='cpu', compute_type='int8', cpu_threads=2, local_files_only=True)
        started = time.perf_counter()
        segments, _ = model.transcribe(np.zeros(8000, np.float32), initial_prompt=plan['prompt'], **plan['asr'])
        list(segments)
        warmups[name] = (time.perf_counter()-started)*1000
        for clip in clips:
            pcm = np.frombuffer(clip['pcm'], dtype='<i2').astype(np.float32)/32768
            for crop, windows in clip['windows'].items():
                transcripts, timings, confidence = [], [], []
                for window in windows:
                    started = time.perf_counter()
                    segments, _ = model.transcribe(pcm[window['start']:window['stop']], initial_prompt=plan['prompt'], **plan['asr'])
                    decoded = list(segments)
                    transcripts.append(' '.join(s.text for s in decoded).strip())
                    timings.append((time.perf_counter()-started)*1000)
                    confidence.append(segment_confidence(decoded))
                text = ' '.join(t for t in transcripts if t)
                rows.append({'model': name, 'crop': crop, 'number': clip['number'],
                             'condition': clip['condition'], 'category': clip['category'],
                             'expected': clip['phrase'], 'text': text, 'windows': windows,
                             'decode_ms': sum(timings), 'segment_decode_ms': timings,
                             'segment_confidence_by_window': confidence,
                             'window_transcripts': transcripts, 'word_alignment_by_window': [],
                             'worker_deadline_exceeded': any(ms > 3000 for ms in timings),
                             **score(clip['phrase'], text)})
        # Finish every primary measurement for this model before alignment.
        # A separate pass can alter segmentation and must be matched explicitly.
        for row in (row for row in rows if row['model'] == name):
            clip = next(clip for clip in clips if clip['number'] == row['number'])
            pcm = np.frombuffer(clip['pcm'], dtype='<i2').astype(np.float32)/32768
            for index, window in enumerate(row['windows']):
                started = time.perf_counter()
                alignment, _ = model.transcribe(pcm[window['start']:window['stop']],
                                                initial_prompt=plan['prompt'],
                                                word_timestamps=True, **plan['asr'])
                aligned = list(alignment)
                alignment_ms = (time.perf_counter()-started)*1000
                aligned_text = ' '.join(s.text for s in aligned).strip()
                row['word_alignment_by_window'].append({
                    'primary_text_agrees': words(aligned_text) == words(row['window_transcripts'][index]),
                    'alignment_ms': alignment_ms, 'text': aligned_text,
                    'words': [{'word': w.word, 'start': w.start, 'end': w.end,
                               'probability': finite(w.probability)}
                              for s in aligned for w in (s.words or [])]})
        del model
    summaries = []
    for name in plan['models']:
        for crop in ['current_100ms', 'longer_1000ms', 'full_clip']:
            for condition in ['quiet', 'overlap']:
                subset = [r for r in rows if (r['model'],r['crop'],r['condition']) == (name,crop,condition)]
                requests = [r for r in subset if r['category']=='request']
                controls = [r for r in subset if r['category']=='silence']
                count = sum(r['reference_words'] for r in requests)
                summary = {'model': name, 'crop': crop, 'condition': condition,
                           'request_clips': len(requests), 'exact_word_clips': sum(r['exact_words'] for r in requests),
                           'aggregate_wer': sum(r['word_edits'] for r in requests)/count if count else None,
                           'first_three_correct': sum(r['first_three_words'] for r in requests),
                           'last_three_correct': sum(r['last_three_words'] for r in requests),
                           'request_clips_without_vad': sum(not r['windows'] for r in requests),
                           'silence_clips': len(controls), 'silence_with_words': sum(r['silence_invented_words'] for r in controls),
                           'median_decode_ms': float(np.median([r['decode_ms'] for r in requests if r['windows']])) if any(r['windows'] for r in requests) else None}
                summaries.append(summary)
                print(json.dumps(summary), flush=True)
    source_digest = hashlib.sha256(args.collection.read_bytes()).hexdigest()
    calibration = [calibration_row(row, source_digest, data['protocol_sha256']) for row in rows]
    from importlib.metadata import version
    environment = {'engine': 'faster-whisper', 'engine_version': version('faster-whisper'),
                   'ctranslate2_version': version('ctranslate2'), 'compute_type': 'int8', 'cpu_threads': 2}
    for row in calibration:
        row.update(**environment, model_sha256=plan['models'][row['model']]['files']['model.bin'])
    report = {'scope': 'Paired adult development experiment; no household, independent onset or latency percentile qualification',
              'fixture_only': data.get('fixture_only', False),
              'complete': data['complete'], 'source_sha256': source_digest,
              'protocol_sha256': data['protocol_sha256'], 'prompt': plan['prompt'], 'asr': plan['asr'],
              'warmup_ms': warmups, 'summaries': summaries, 'cases': rows, 'api_spend_usd': 0,
              'calibration_rows': calibration,
              'decoder_environment': environment, 'models': plan['models'],
              'limitations': ['No expected phrase is passed as a model hint.',
                             'All VAD segments are retained; early echo detections are not silently removed.',
                             'Longer crop assumes a larger ring; runtime defaults are unchanged.',
                             'Full clip is a boundary control; echo or extra context may change decoding.',
                             'Words are normalized for punctuation/case only; WER does not independently establish meaning.',
                             'Tiny then base use warmed CPU int8/two threads; thermal/order effects are uncontrolled.',
                             'A fresh varied follow-up set is required before promoting a setting.']}
    out = Path('.tavi/private-speech-analysis')
    out.mkdir(parents=True, exist_ok=True)
    path = out/('speech-check-'+source_digest[:16]+'.json')
    path.write_text(json.dumps(report, indent=2)+'\n')
    with path.with_suffix('.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(calibration[0]))
        writer.writeheader()
        writer.writerows(calibration)
    print(json.dumps({'private_report': str(path), 'calibration_csv': str(path.with_suffix('.csv')), 'api_spend_usd': 0}))


if __name__ == '__main__':
    main()
