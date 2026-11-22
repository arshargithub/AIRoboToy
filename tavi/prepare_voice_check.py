"""Prepare fixed synthetic listening samples from completed local benchmarks."""
import argparse
import array
import hashlib
import json
import math
from pathlib import Path
import wave

from .benchmark_conversation_voice import CASES


def prepare(mac_report, piper_report):
    mac = json.loads(mac_report.read_text()); piper = json.loads(piper_report.read_text())
    if mac.get('kind') != 'paprika_offline_voice_latency' or piper.get('model') != 'piper' or not piper.get('summary'):
        raise ValueError('Expected completed synthetic voice benchmarks')
    texts = {key: ''.join(parts) for key, parts in CASES}
    output = Path('.tavi/voice-check'); output.mkdir(parents=True, exist_ok=True)
    trials = []
    order = [('A','short_story'), ('B','short_story'), ('B','short_first_sentence'), ('A','short_first_sentence')]
    for index, (voice, key) in enumerate(order, 1):
        if voice == 'A':
            row = next(r for r in mac['pairs'] if r['case'] == key and r['repeat'] == 1)
            path = mac_report.parent/row['whole']['outputs'][0]['wav']
        else:
            row = next(r for r in piper['trials'] if r['case'] == key and r['repeat'] == 1)
            if row['text'] != texts[key]: raise ValueError('Synthetic text mismatch')
            path = piper_report.parent/row['wav']
        with wave.open(str(path)) as audio:
            rate = audio.getframerate()
            if audio.getnchannels() != 1 or audio.getsampwidth() != 2 or rate not in (16000,22050):
                raise ValueError('Unexpected synthetic sample format')
            if not 0 < audio.getnframes() <= rate*30: raise ValueError('Synthetic sample too long')
            samples = array.array('h'); samples.frombytes(audio.readframes(audio.getnframes()))
        peak = max(abs(x) for x in samples); rms = math.sqrt(sum(x*x for x in samples)/len(samples))
        if not peak: raise ValueError('Silent listening sample')
        gain = min(4, .08*32768/rms, .95*32767/peak)
        destination = output/f'sample-{index}.wav'
        with wave.open(str(destination), 'wb') as audio:
            audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(rate)
            audio.writeframes(array.array('h', (round(x*gain) for x in samples)).tobytes())
        trials.append({'id': f'sample-{index}', 'voice': voice, 'text': texts[key],
            'src': f'/voice-check/sample-{index}.wav', 'case': key, 'gain': gain,
            'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'sha256': hashlib.sha256(destination.read_bytes()).hexdigest()})
    plan = {'schema_version': 1, 'id': 'paprika-voice-quality-v1', 'kind': 'paprika_voice_quality_check',
            'trials': trials, 'voices': {'A': 'Mac Samantha', 'B': 'Piper LJ Speech medium'},
            'scope': 'Fixed synthetic speech only; no microphone/cloud. Bounded whole-clip RMS normalization, not perceptual loudness matching; timing benchmarks use originals.'}
    path = Path(__file__).with_name('web')/'voice-check-protocol.json'
    path.write_text(json.dumps(plan, indent=2)+'\n')
    print('Four synthetic local listening samples and protocol prepared.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mac-report', type=Path, required=True)
    parser.add_argument('--piper-report', type=Path, required=True)
    args = parser.parse_args(); prepare(args.mac_report, args.piper_report)


if __name__ == '__main__': main()
