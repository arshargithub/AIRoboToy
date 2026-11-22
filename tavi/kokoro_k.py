"""Pinned provisional K voice: 65% af_heart, 35% af_nicole, local CPU only."""
import hashlib
import json
from pathlib import Path

from .neural_voice import verify_assets
from .voice_pronunciation import audition_phonemes
from .kokoro_phonemes import prepare_sentences
from .speech_errors import SpeechWorkerError

MANIFEST=Path(__file__).with_name('kokoro_k_manifest.json')
ROOT=Path('.tavi/models/kokoro-k-35')


def prepare_assets():
    """Explicit developer setup; dynamic synthesis never writes to disk."""
    import numpy as np
    from .prepare_voice_texture import blend_styles
    source=verify_assets('kokoro')
    manifest=json.loads(MANIFEST.read_text())
    styles=np.fromfile(source/'voices.bin',dtype='<f4').reshape(54,510,256)
    data=blend_styles(styles,(.35,)).astype('<f4').tobytes()
    if hashlib.sha256(data).hexdigest()!=manifest['derived_styles_sha256']:
        raise ValueError('K style derivation differs from the approved configuration')
    ROOT.mkdir(parents=True,exist_ok=True);path=ROOT/'voices.bin'
    if path.exists() and path.read_bytes()!=data:raise ValueError('Existing K styles changed; inspect before replacing')
    if not path.exists():path.write_bytes(data)


class KokoroK:
    def __init__(self,threads=2):
        import sherpa_onnx as s
        from piper.phonemize_espeak import EspeakPhonemizer
        source=verify_assets('kokoro');manifest=json.loads(MANIFEST.read_text())
        path=ROOT/'voices.bin'
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=manifest['derived_styles_sha256']:
            raise ValueError('Run python -m tavi.kokoro_k to prepare the pinned K style')
        config=s.OfflineTtsConfig(model=s.OfflineTtsModelConfig(kokoro=s.OfflineTtsKokoroModelConfig(
            model=str(source/'model.int8.onnx'),voices=str(path),tokens=str(source/'tokens.txt')),
            num_threads=threads,provider='cpu'))
        if not config.validate():raise ValueError('Invalid K speech configuration')
        self.engine=s.OfflineTts(config);self.phonemizer=EspeakPhonemizer()
        self.tokens={line.rsplit(' ',1)[0] for line in (source/'tokens.txt').read_text().splitlines() if line}

    def generate(self,text):
        import sherpa_onnx as s
        if not isinstance(text,str) or not 0<len(text)<=480:raise ValueError('Reply exceeds K voice text bound')
        # The spoken-name override covers runtime casing as well as display Paprika.
        import re
        spoken=re.sub(r'\bpaprika\b','Paprika',text,flags=re.I)
        phones=[list(s) for s in prepare_sentences(audition_phonemes(self.phonemizer,spoken))]
        if any(c not in self.tokens for sentence in phones for c in sentence):
            raise SpeechWorkerError('unsupported_phoneme')
        config=s.GenerationConfig();config.sid=0;config.silence_scale=1
        config.phoneme_codepoints=[[ord(c) for c in sentence] for sentence in phones]
        return self.engine.generate('',config)


if __name__=='__main__':
    prepare_assets();print('Pinned K styles prepared locally; source model and historical auditions unchanged.')
