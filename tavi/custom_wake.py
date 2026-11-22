"""Local TAH-vee experiment: frozen speech embeddings plus a small trained head.

Frontend tensor conventions follow openWakeWord v0.6.0 AudioFeatures. This
implementation uses identical fixed two-second windows for training/inference.
"""
import hashlib
import json
from pathlib import Path
import time
import numpy as np
import onnxruntime as ort

FRONTEND={
 'melspectrogram.onnx':'ba2b0e0f8b7b875369a2c89cb13360ff53bac436f2895cced9f479fa65eb176f',
 'embedding_model.onnx':'70d164290c1d095d1d4ee149bc5e00543250a7316b59f31d056cff7bd3075c1f',
}

class Features:
    def __init__(self, root=Path('.tavi/models/custom'), *, mode='pooled'):
        if mode not in ('pooled','temporal'):raise ValueError('Unknown feature mode')
        self.mode=mode
        options=ort.SessionOptions();options.intra_op_num_threads=options.inter_op_num_threads=1
        sessions=[]
        for name,digest in FRONTEND.items():
            path=root/name
            if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('Custom frontend checksum mismatch')
            sessions.append(ort.InferenceSession(str(path),options,providers=['CPUExecutionProvider']))
        self.mel,self.embedding=sessions
    def extract(self, pcm):
        x=np.asarray(pcm,dtype=np.int16)
        if x.shape!=(32000,):raise ValueError('Expected exactly two seconds of mono PCM16')
        spec=self.mel.run(None,{'input':x.astype(np.float32)[None,:]})[0].squeeze()/10+2
        end=len(spec)
        windows=np.stack([spec[end-76-8*i:end-8*i] for i in reversed(range(16))]).astype(np.float32)[...,None]
        emb=self.embedding.run(None,{'input_1':windows})[0].reshape(16,96)
        if self.mode=='temporal':return emb.reshape(-1).astype(np.float32)
        return np.concatenate((emb.mean(axis=0),emb.max(axis=0),emb.std(axis=0),emb[-1])).astype(np.float32)

class DenseHead:
    def __init__(self, weights):
        self.weights=weights
        if np.any(weights['scale']<=0) or not all(np.isfinite(v).all() for v in weights.values()):
            raise ValueError('Invalid classifier weights')
    def score(self, vector):
        x=(vector-self.weights['mean'])/self.weights['scale']
        if 'sv' in self.weights:
            diff=self.weights['sv']-x
            decision=np.exp(-self.weights['gamma']*np.sum(diff*diff,axis=1))@self.weights['dual']+self.weights['intercept']
            return float(1/(1+np.exp(-np.clip(decision,-40,40))))
        i=0
        while f'w{i}' in self.weights:
            x=x@self.weights[f'w{i}']+self.weights[f'b{i}'];i+=1
            if f'w{i}' in self.weights:x=np.maximum(x,0)
        return float(1/(1+np.exp(-np.clip(x[0],-40,40))))

class CustomWake:
    def __init__(self,root=Path('.tavi/models/custom'), *, allow_unqualified=False):
        manifest=json.loads((root/'head.json').read_text())
        if manifest['status']!='trial_candidate':raise ValueError('Custom head has not passed the development gate')
        if not allow_unqualified and manifest.get('streaming_status')!='passed':raise ValueError('Custom head has not passed streaming evaluation')
        if hashlib.sha256((root/'head.npz').read_bytes()).hexdigest()!=manifest['sha256']:raise ValueError('Custom head checksum mismatch')
        self.features=Features(root,mode=manifest.get('feature_mode','pooled'))
        with np.load(root/'head.npz',allow_pickle=False) as archive:
            self.head=DenseHead(dict(archive))
        self.threshold=manifest['threshold'];self.reset()
    def reset(self):
        self.audio=np.zeros(32000,dtype=np.int16);self.pending=0;self.high=0;self.low=0;self.armed=True;self.samples_since_hit=32000;self.score=0.;self.inference_ms=0.
    def probability(self,pcm):
        return self.head.score(self.features.extract(pcm))
    def feed(self,pcm, *, speech_allowed=True):
        samples=np.frombuffer(pcm,dtype='<i2');n=len(samples)
        if n!=512:raise ValueError('Expected one 32 ms frame')
        self.audio[:-n]=self.audio[n:];self.audio[-n:]=samples;self.pending+=n;self.samples_since_hit+=n
        if self.pending<1280:return ''
        self.pending-=1280;started=time.perf_counter();self.score=self.probability(self.audio);self.inference_ms=(time.perf_counter()-started)*1000
        self.high=self.high+1 if self.score>=self.threshold and speech_allowed else 0
        self.low=self.low+1 if self.score<self.threshold or not speech_allowed else 0
        if self.low>=3 and self.samples_since_hit>=24000:self.armed=True
        if self.armed and self.high>=2:self.armed=False;self.samples_since_hit=0;return 'TAVI'
        return ''

def setup():
    from urllib.request import urlopen
    root=Path('.tavi/models/custom');root.mkdir(parents=True,exist_ok=True)
    for name,digest in FRONTEND.items():
        path=root/name
        if not path.exists():
            with urlopen('https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/'+name,timeout=60) as r:data=r.read(30_000_000)
            if hashlib.sha256(data).hexdigest()!=digest:raise ValueError('Frontend download checksum mismatch')
            path.write_bytes(data)
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('Frontend checksum mismatch')

if __name__=='__main__':setup()
