"""Local speech diagnostics, never silence trimming or perceptual acceptance."""
from array import array
from io import BytesIO
import hashlib
import math
import wave
from tavi.sentence_chunks import SentenceChunks

THRESHOLDS=(-50,-40,-30)


def split(text):
    s=SentenceChunks(minimum=32)
    return s.feed(text)+s.finish()


def read_pcm(wav):
    with wave.open(BytesIO(wav)) as w:
        if (w.getframerate(),w.getnchannels(),w.getsampwidth())!=(24000,1,2):raise ValueError('Expected pinned K PCM format')
        raw=w.readframes(w.getnframes())
    a=array('h');a.frombytes(raw);return a


def write_pcm(samples):
    out=BytesIO()
    with wave.open(out,'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000);w.writeframes(samples.tobytes())
    return out.getvalue()


def join(wavs):
    samples=array('h')
    for wav in wavs:samples.extend(read_pcm(wav))
    return write_pcm(samples)


def edges(wav):
    """10ms RMS blocks, at least two successive active blocks; no editing.

    Quiet phonemes can fall below any selected threshold. This is a sensitivity
    diagnostic and must never be used as an automatic safe-to-trim boundary.
    """
    a=read_pcm(wav);rms=[]
    for start in range(0,len(a),240):
        block=a[start:start+240];rms.append(math.sqrt(sum(v*v for v in block)/len(block))/32768)
    rows={}
    for db in THRESHOLDS:
        threshold=10**(db/20);runs=[]
        for i in range(len(rms)-1):
            if rms[i]>threshold and rms[i+1]>threshold:runs.extend((i,i+1))
        rows[str(db)]={'leading_ms':min(runs)*10 if runs else None,
            'trailing_ms':max(0,(len(a)-min(len(a),(max(runs)+1)*240))/24) if runs else None}
    return {'duration_ms':len(a)/24,'pcm_sha256':hashlib.sha256(a.tobytes()).hexdigest(),'threshold_edges_ms':rows}
