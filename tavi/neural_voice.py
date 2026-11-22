"""Local-only Sherpa neural voice candidates, shared by benchmark and worker.

No downloads or private reference audio are permitted here. Setup installs the
pinned public models and the published Alba MacKenna casual voice reference.
"""
from io import BytesIO
import json
from pathlib import Path
import hashlib
import wave


ROOT = Path('.tavi/models')
MANIFEST = Path(__file__).with_name('neural_voice_manifest.json')


def verify_assets(name):
    manifest = json.loads(MANIFEST.read_text())
    entry = manifest['models'][name]
    root = ROOT / entry['directory']
    for relative, expected in entry['files'].items():
        path = root / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Local voice asset missing or changed: '+relative)
    return root


def create_engine(name, *, threads=2):
    import numpy as np
    root = verify_assets(name)
    if name == 'piper':
        import onnxruntime as ort
        from piper import PiperVoice
        from piper.config import PiperConfig
        from piper.phonemize_espeak import ESPEAK_DATA_DIR
        settings = ort.SessionOptions()
        settings.intra_op_num_threads = threads; settings.inter_op_num_threads = 1
        voice = PiperVoice(config=PiperConfig.from_dict(json.loads((root/'en_US-ljspeech-medium.onnx.json').read_text())),
                          session=ort.InferenceSession(str(root/'en_US-ljspeech-medium.onnx'),
                              sess_options=settings, providers=['CPUExecutionProvider']),
                          espeak_data_dir=ESPEAK_DATA_DIR, download_dir=root)
        return PiperEngine(voice), None
    import sherpa_onnx as s
    if name == 'pocket':
        model = s.OfflineTtsModelConfig(pocket=s.OfflineTtsPocketModelConfig(
            lm_flow=str(root/'lm_flow.int8.onnx'), lm_main=str(root/'lm_main.int8.onnx'),
            encoder=str(root/'encoder.onnx'), decoder=str(root/'decoder.int8.onnx'),
            text_conditioner=str(root/'text_conditioner.onnx'), vocab_json=str(root/'vocab.json'),
            token_scores_json=str(root/'token_scores.json')), num_threads=threads, provider='cpu')
        config = s.GenerationConfig()
        with wave.open(str(root/'alba-casual.wav')) as audio:
            if audio.getsampwidth() != 2 or audio.getnchannels() != 1:
                raise ValueError('Unexpected published voice reference format')
            config.reference_audio = np.frombuffer(audio.readframes(audio.getnframes()), dtype='<i2').astype('float32')/32768
            config.reference_sample_rate = audio.getframerate()
        config.num_steps = 5
        # Callback audio precedes Sherpa's final silence-compression pass.
        # Disable that offline-only transform so streaming and final PCM agree.
        config.silence_scale = 1
    elif name == 'kokoro':
        model = s.OfflineTtsModelConfig(kokoro=s.OfflineTtsKokoroModelConfig(
            model=str(root/'model.int8.onnx'), voices=str(root/'voices.bin'),
            tokens=str(root/'tokens.txt'), lexicon=str(root/'lexicon-us-en.txt')),
            num_threads=threads, provider='cpu')
        config = None
    else:
        raise ValueError('Unknown local voice')
    settings = s.OfflineTtsConfig(model=model, max_num_sentences=1)
    if not settings.validate():
        raise ValueError('Invalid local neural voice settings')
    return s.OfflineTts(settings), config


class PiperEngine:
    def __init__(self, voice):
        self.voice = voice
        self.sample_rate = voice.config.sample_rate

    def generate(self, text, sid=0, speed=1, callback=None):
        import numpy as np
        from types import SimpleNamespace
        parts = []; count = 0
        for part in self.voice.synthesize(text):
            samples = np.asarray(part.audio_float_array, dtype='float32')
            count += len(samples)
            if count > 30*self.sample_rate:
                raise ValueError('Local voice exceeds thirty seconds')
            parts.append(samples.copy())
            if callback is not None and not callback(samples, 0):
                break
        return SimpleNamespace(samples=np.concatenate(parts) if parts else np.array([], dtype='float32'),
                               sample_rate=self.sample_rate)


def generate(engine, config, text, callback=None):
    if not isinstance(text, str) or not 0 < len(text) <= 480:
        raise ValueError('Reply exceeds local neural voice text bound')
    if config is None:
        return engine.generate(text, sid=0, speed=1, callback=callback)
    return engine.generate(text, config, callback=callback)


def pcm_wave(samples, sample_rate):
    import numpy as np
    samples = np.asarray(samples, dtype='float32')
    if (samples.ndim != 1 or not 0 < len(samples) <= sample_rate*30
            or sample_rate not in (16000, 22050, 24000) or not np.all(np.isfinite(samples))):
        raise ValueError('Invalid bounded local voice samples')
    raw = np.rint(np.clip(samples, -1, 1)*32767).astype('<i2').tobytes()
    out = BytesIO()
    with wave.open(out, 'wb') as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(sample_rate)
        audio.writeframes(raw)
    return out.getvalue()
