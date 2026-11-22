"""Create a fixed synthetic Paprika playback fixture using local macOS tools."""
from pathlib import Path
import struct
import subprocess
import wave

TEXT = ('Hello, I am Paprika. This is my test voice. Please stay silent while I talk. '
        'We are checking whether my own voice accidentally wakes me up. '
        'Paprika is ready to listen when this test finishes.')


def main():
    root = Path('.tavi/audio')
    root.mkdir(parents=True, exist_ok=True)
    target = root / 'paprika-reference.wav'
    if not target.exists():
        source = root / 'paprika-reference.aiff'
        temporary = root / 'paprika-reference.tmp.wav'
        subprocess.run(['say', '-v', 'Samantha', '-r', '175', '-o', str(source), TEXT], check=True)
        subprocess.run(['afconvert', '-f', 'WAVE', '-d', 'LEI16@16000', '-c', '1', str(source), str(temporary)], check=True)
        with wave.open(str(temporary)) as audio:
            if audio.getframerate() != 16000 or audio.getnchannels() != 1 or audio.getsampwidth() != 2:
                raise ValueError('Unexpected synthetic fixture format')
            raw = audio.readframes(audio.getnframes())
            if len(raw) < 16000 or max(abs(v[0]) for v in struct.iter_unpack('<h', raw)) < 100:
                raise ValueError('Local speech synthesis produced no usable audio')
        temporary.replace(target)
    with wave.open(str(target)) as audio:
        print(f'Paprika synthetic test voice ready: {audio.getnframes()/16000:.1f} seconds; no human recording or paid API')


if __name__ == '__main__': main()
