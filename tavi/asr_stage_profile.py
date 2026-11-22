"""Optional synchronized native-stage profiling, never a decoding policy."""
from contextlib import contextmanager
import importlib
import time


@contextmanager
def synchronized_stages(enabled):
    stages = {}
    if not enabled:
        yield stages
        return
    import mlx.core as mx
    module = importlib.import_module('mlx_whisper.transcribe')
    from mlx_whisper.decoding import DecodingTask
    originals = [(module, 'log_mel_spectrogram', module.log_mel_spectrogram),
                 (DecodingTask, '_get_audio_features', DecodingTask._get_audio_features),
                 (DecodingTask, '_main_loop', DecodingTask._main_loop)]
    def wrapped(function, key):
        def call(*args, **kwargs):
            started = time.perf_counter()
            result = function(*args, **kwargs)
            mx.eval(*(result if isinstance(result, tuple) else (result,)))
            mx.synchronize()
            stages[key] = stages.get(key, 0) + (time.perf_counter()-started)*1000
            return result
        return call
    try:
        for (obj, name, function), key in zip(originals, ('mel_ms','encoder_ms','token_loop_ms')):
            setattr(obj, name, wrapped(function, key))
        yield stages
    finally:
        for obj, name, function in originals:
            setattr(obj, name, function)
