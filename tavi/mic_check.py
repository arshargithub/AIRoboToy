"""Validate local capture-quality recordings and summarize human ratings; no ASR."""
import argparse
import base64
import hashlib
import json
import math
from pathlib import Path
import struct

PROFILES = [('current', True, True), ('echo_only', True, False), ('unprocessed_request', False, False)]


def analyze(path):
    if path.stat().st_size > 4_000_000:
        raise ValueError('Microphone check exceeds its six-clip bound')
    data = json.loads(path.read_text())
    expected = {'schema_version': 1, 'kind': 'paprika_private_microphone_check',
                'protocol_id': 'microphone-quality-v1', 'sample_rate': 16000,
                'format': 'mono_pcm16le_base64'}
    if any(data.get(k) != v for k, v in expected.items()):
        raise ValueError('Unexpected microphone-check format')
    clips, rounds = data.get('clips'), data.get('rounds')
    if not isinstance(clips, list) or not 1 <= len(clips) <= 6 or not isinstance(rounds, list) or not 1 <= len(rounds) <= 3:
        raise ValueError('Invalid clip/round count')
    if type(data.get('complete')) is not bool or (data['complete'] and len(clips) != 6):
        raise ValueError('Invalid completion flag')
    summaries = []
    for index, clip in enumerate(clips):
        round_index = index//2
        if round_index >= len(rounds):
            raise ValueError('Missing microphone settings for a clip')
        profile, echo, noise = PROFILES[round_index]
        if (clip.get('number'), clip.get('round'), clip.get('profile'), clip.get('position')) != (index+1, round_index+1, profile, 'first' if index%2 == 0 else 'later'):
            raise ValueError('Clip order differs from the microphone-check protocol')
        raw = base64.b64decode(clip.get('pcm_base64', ''), validate=True)
        if len(raw) != 250*1024 or clip.get('sample_count') != 250*512:
            raise ValueError('A complete clip must contain eight seconds of PCM16')
        start, cue = clip.get('capture_start_frame'), clip.get('cue_context_frame')
        if type(start) is not int or start < 0 or type(cue) is not int or cue-start != 64*512:
            raise ValueError('Invalid cue/capture frame metadata')
        rating = clip.get('quality_rating')
        if rating not in ('clear', 'impaired', 'unsure', 'unrated'):
            raise ValueError('Unknown human quality rating')
        record = rounds[round_index]
        requested = {'echoCancellation': echo, 'noiseSuppression': noise, 'autoGainControl': False}
        if record.get('requested') != requested or record.get('profile') != profile:
            raise ValueError('Microphone settings differ from the fixed profile')
        reported = record.get('reported', {})
        samples = [x[0] for x in struct.iter_unpack('<h', raw)]
        rms = math.sqrt(sum(x*x for x in samples)/len(samples))/32768
        summaries.append({'number': index+1, 'round': round_index+1, 'profile': profile,
                          'position': clip['position'], 'human_quality_rating': rating,
                          'ms_since_mic_open_at_capture': clip.get('ms_since_mic_open_at_capture'),
                          'settings_verified': all(reported.get(k) is v for k, v in requested.items()),
                          'reported': reported, 'rms_dbfs': 20*math.log10(rms) if rms else None,
                          'peak_fraction': max(abs(x) for x in samples)/32768,
                          'full_scale_samples': sum(abs(x) >= 32767 for x in samples)})
    return {'scope': 'Local human-rated capture-quality diagnosis; not an acoustic acceptance test',
            'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'complete': data['complete'], 'clips': summaries, 'api_spend_usd': 0,
            'ratings_complete': all(c['human_quality_rating'] != 'unrated' for c in summaries),
            'limitations': ['First/later are relative to a microphone opening, not a guaranteed hardware cold start.',
                           'Profiles run in a fixed order; OS state and time can confound a settings effect.',
                           'Browser constraints can be ignored; unverified settings cannot establish an AEC/NS contrast.',
                           'Human ratings are not blinded and the phrase is repeated.',
                           'RMS and peak statistics do not prove or rule out audible corruption.',
                           'Quiet-room results do not establish echo rejection or safe interruption during playback.',
                           'Runtime microphone settings remain unchanged.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('collection', type=Path)
    args = parser.parse_args()
    result = analyze(args.collection)
    out = Path('.tavi/private-microphone-analysis')
    out.mkdir(parents=True, exist_ok=True)
    path = out/('microphone-'+result['source_sha256'][:16]+'.json')
    path.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
    print(json.dumps({'private_report': str(path)}))


if __name__ == '__main__':
    main()
