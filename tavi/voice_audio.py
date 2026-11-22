"""Bounded shared speech level matching; no perceptual loudness guarantee."""
import array
from io import BytesIO
import math
import wave


def level_match(data):
    with wave.open(BytesIO(data)) as audio:
        rate = audio.getframerate()
        if audio.getnchannels()!=1 or audio.getsampwidth()!=2 or not 0<audio.getnframes()<=rate*30:
            raise ValueError('Invalid audition audio')
        samples=array.array('h'); samples.frombytes(audio.readframes(audio.getnframes()))
    peak=max(abs(x) for x in samples); rms=math.sqrt(sum(x*x for x in samples)/len(samples))
    if not rms: raise ValueError('Silent audition sample')
    gain=min(4,.08*32768/rms,.95*32767/peak)
    out=BytesIO()
    with wave.open(out,'wb') as audio:
        audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(rate)
        audio.writeframes(array.array('h',(round(x*gain) for x in samples)).tobytes())
    return out.getvalue(),gain

