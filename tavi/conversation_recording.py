"""Extract opted-in conversation audio locally, preserving ASR correlation IDs."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import wave


def write_wave(path, pcm):
    with wave.open(str(path), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(pcm)


def extract(path, output_root=Path('.tavi/private-conversation-audio')):
    if path.stat().st_size > 16_000_000:
        raise ValueError('Conversation diagnostic file exceeds its local size bound')
    source = path.read_bytes()
    report = json.loads(source)
    if report.get('schema_version') != 1 or report.get('kind') != 'paprika_controlled_conversation_diagnostics':
        raise ValueError('Unexpected conversation diagnostic format')
    runs = report.get('runs')
    if not isinstance(runs, list) or not 1 <= len(runs) <= 12:
        raise ValueError('Invalid conversation run count')
    validated = []
    for index, run in enumerate(runs):
        audio = run.get('local_audio')
        if audio is None:
            continue
        if run.get('local_audio_recording', {}).get('enabled') is not True:
            raise ValueError('Audio lacks its explicit recording opt-in metadata')
        if (audio.get('sample_rate'), audio.get('format'), audio.get('closed')) != (16000, 'mono_pcm16le_base64', True):
            raise ValueError('Invalid audio format or recording still open')
        samples = audio.get('sample_count')
        if type(samples) is not int or not 0 < samples <= 5625*512 or samples % 512:
            raise ValueError('Invalid recording sample count')
        start, end = audio.get('start_context_frame'), audio.get('end_context_frame')
        if type(start) is not int or start < 0 or type(end) is not int or end-start != samples:
            raise ValueError('Recording timeline is inconsistent')
        if audio.get('first_sequence') != 0 or audio.get('last_sequence') != samples//512-1:
            raise ValueError('Recording must start at ASR sample zero with contiguous frames')
        pcm = base64.b64decode(audio.get('pcm_base64', ''), validate=True)
        if len(pcm) != samples*2:
            raise ValueError('Recording PCM does not match its declared sample count')
        recognized = run.get('recognition_results', [])
        if not isinstance(recognized, list) or len(recognized) > 120:
            raise ValueError('Invalid recognition result count')
        validated.append((index, run, audio, pcm))
    if not validated:
        raise ValueError('No opted-in local audio found; timings-only files contain no recording')
    digest = hashlib.sha256(source).hexdigest()
    folder = output_root/('conversation-'+digest[:16])
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {'source_sha256': digest, 'audio_egress': 'none', 'api_spend_usd': 0, 'runs': [],
                'scope': 'Local recorded input and decoder diagnostics; no automatic quality or understanding verdict'}
    for index, run, audio, pcm in validated:
        full_path = folder/f'run-{index+1:02d}-microphone.wav'
        write_wave(full_path, pcm)
        entry = {'run_number': index+1, 'microphone_wav': str(full_path), 'settings': run.get('settings'),
                 'asr_run_id': run.get('asr_run_id'), 'recording': {k:v for k,v in audio.items() if k != 'pcm_base64'},
                 'guided_test': run.get('guided_test'), 'recognitions': [],
                 'recognition_results_dropped': run.get('recognition_results_dropped', 0),
                 'events': run.get('events', [])}
        for number, event in enumerate(run.get('recognition_results', []), 1):
            case = dict(event)
            start, count = event.get('audio_start_sample'), event.get('audio_samples')
            same_run = not event.get('asr_run_id') or not run.get('asr_run_id') or event['asr_run_id'] == run['asr_run_id']
            if not same_run or type(start) is not int or type(count) is not int or start < 0 or count <= 0 or start+count > audio['sample_count']:
                case['slice_unavailable'] = 'Missing, out-of-range or mismatched ASR bounds; no slice fabricated'
            else:
                exact = folder/f'run-{index+1:02d}-recognition-{number:03d}-asr-input.wav'
                context = folder/f'run-{index+1:02d}-recognition-{number:03d}-context.wav'
                write_wave(exact, pcm[start*2:(start+count)*2])
                lead, tail = max(0, start-16000), min(audio['sample_count'], start+count+3200)
                write_wave(context, pcm[lead*2:tail*2])
                case.update(asr_input_wav=str(exact), context_wav=str(context),
                            context_start_sample=lead, context_end_sample=tail)
            recognition_id = event.get('recognition_id')
            case['accepted_turns'] = [turn for turn in report.get('accepted_text', [])
                                      if recognition_id and turn.get('recognition_id') == recognition_id]
            case['human_recognition_reviews'] = [review for review in report.get('reviews', [])
                                                 if recognition_id and review.get('recognition_id') == recognition_id]
            entry['recognitions'].append(case)
        manifest['runs'].append(entry)
    manifest['limitations'] = ['Input is already browser-processed, not raw hardware audio.',
                               'Recording starts at listening-ready, not before microphone acquisition.',
                               'Context windows are diagnostic; the recognizer used the exact ASR window.',
                               'Guided overall outcomes are not automatic transcription-correctness labels.',
                               'Browser/detector timings do not establish independently measured acoustic latency.']
    manifest_path = folder/'manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=2)+'\n')
    return manifest_path, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('diagnostics', type=Path)
    args = parser.parse_args()
    path, manifest = extract(args.diagnostics)
    print(json.dumps({'private_manifest': str(path), 'recorded_runs': len(manifest['runs']),
                      'recognition_records': sum(len(run['recognitions']) for run in manifest['runs']),
                      'api_spend_usd': 0}))


if __name__ == '__main__':
    main()
