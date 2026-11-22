"""Apple Silicon K worker: same style/phonemes, pinned local Kokoro weights."""
import hashlib
import json
import os
from pathlib import Path
import re

os.environ['HF_HUB_OFFLINE']='1'
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'

from .kokoro_k import ROOT, MANIFEST
from .voice_pronunciation import audition_phonemes
from .kokoro_phonemes import prepare_sentences
from .speech_errors import SpeechWorkerError


class MLXK:
    def __init__(self):
        import mlx.core as mx
        import numpy as np
        from mlx_audio.tts.utils import load_model
        from piper.phonemize_espeak import EspeakPhonemizer
        model_root=Path('.tavi/models/kokoro-mlx-bf16')
        manifest=json.loads(Path(__file__).with_name('kokoro_mlx_manifest.json').read_text())
        for row in manifest['files']:
            path=model_root/row['path']
            if not path.is_file() or path.stat().st_size!=row['size'] or hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:
                raise ValueError('Pinned K MLX model missing or changed')
        data=(ROOT/'voices.bin').read_bytes()
        if hashlib.sha256(data).hexdigest()!=json.loads(MANIFEST.read_text())['derived_styles_sha256']:
            raise ValueError('Pinned K style missing or changed')
        mx.set_memory_limit(4*1024**3);mx.set_cache_limit(256*1024**2)
        self.model=load_model(model_root,lazy=False,strict=True);self.model.eval()
        self.styles=np.frombuffer(data,dtype='<f4').reshape(54,510,256)[0].copy()
        self.phonemizer=EspeakPhonemizer()

    def generate(self,text):
        import mlx.core as mx
        import numpy as np
        from types import SimpleNamespace
        if not isinstance(text,str) or not 0<len(text)<=480:raise ValueError('K text exceeds its bound')
        phones=audition_phonemes(self.phonemizer,re.sub(r'\bpaprika\b','Paprika',text,flags=re.I))
        mx.random.seed(0);parts=[];count=0
        for ps in prepare_sentences(phones):
            if any(c not in self.model.vocab for c in ps):raise SpeechWorkerError('unsupported_phoneme')
            audio=self.model(ps,mx.array(self.styles[len(ps)-1:len(ps)]))
            samples=np.array(audio,dtype=np.float32).reshape(-1);count+=len(samples)
            if count>720000:raise SpeechWorkerError('oversized_audio')
            parts.append(samples)
        if not parts:raise ValueError('K produced no speech')
        return SimpleNamespace(samples=np.concatenate(parts),sample_rate=24000)
