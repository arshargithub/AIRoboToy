"""Offline, in-memory final ASR worker. No files containing speech are written."""
import base64
import argparse
from contextlib import redirect_stdout
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

os.environ.update(HF_HUB_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1',
                  HF_HUB_DISABLE_IMPLICIT_TOKEN='1', TRANSFORMERS_OFFLINE='1')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--cache-mib',type=int,choices=(256,1024),default=256)
    parser.add_argument('--wired-mib',type=int,choices=(0,3072),default=0)
    parser.add_argument('--profile-stages',action='store_true')
    parser.add_argument('--encoder-attention',choices=('standard','fused'),default='standard')
    args=parser.parse_args()
    import mlx.core as mx
    import mlx_whisper
    import numpy as np
    from mlx_whisper.transcribe import ModelHolder
    from .asr_confidence import segment_confidence
    from .asr_stage_profile import synchronized_stages
    spec = next(m for m in json.loads(Path('tavi/asr_mlx_manifest.json').read_text())['models']
                if m['id'] == 'turbo')
    root = Path(spec['path'])
    for filename, info in spec['files'].items():
        path = root / filename
        h = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024*1024), b''):
                h.update(block)
        if path.stat().st_size != info['size'] or h.hexdigest() != info['sha256']:
            raise ValueError('Pinned turbo model checksum changed')
    mx.set_memory_limit(6*1024**3)
    mx.set_cache_limit(args.cache_mib*1024**2)
    if args.wired_mib:
        if args.wired_mib*1024**2 >= mx.device_info()['memory_size']:
            raise ValueError('Invalid process wired-memory bound')
        mx.set_wired_limit(args.wired_mib*1024**2)
    with redirect_stdout(sys.stderr):
        model=ModelHolder.get_model(str(root), mx.float16)
        if args.encoder_attention=='fused':
            from .fused_whisper_encoder import install
            install(model)
    profile = {'model': 'large-v3-turbo', 'engine': 'mlx-whisper',
               'engine_version': version('mlx-whisper'), 'mlx_version':version('mlx'),
               'model_sha256':spec['files']['weights.safetensors']['sha256'], 'compute_type': 'float16',
               'revision': spec['revision'], 'prompt': None,
               'language': 'en', 'temperature': 0, 'condition_on_previous_text': False,
               'cache_mib':args.cache_mib,'wired_mib':args.wired_mib,
               'encoder_attention':args.encoder_attention,
               'synchronized_stage_profiling':args.profile_stages}
    print(json.dumps({'ready': True, 'protocol': 1, 'profile': profile}), flush=True)
    for line in sys.stdin.buffer:
        if len(line) > 900_000:
            raise ValueError('Oversized ASR input')
        request = json.loads(line)
        try:
            began=time.perf_counter()
            pcm = base64.b64decode(request['pcm'], validate=True)
            if not 0 < len(pcm) <= 640000 or len(pcm) % 2:
                raise ValueError('Invalid PCM bound')
            audio = np.frombuffer(pcm, dtype='<i2').astype(np.float32)/32768
            converted=time.perf_counter()
            with redirect_stdout(sys.stderr), synchronized_stages(args.profile_stages) as stages:
                result = mlx_whisper.transcribe(audio, path_or_hf_repo=str(root),
                    language='en', task='transcribe', temperature=0,
                    condition_on_previous_text=False, initial_prompt=None,
                    word_timestamps=False, fp16=True, verbose=None)
                transcribed=time.perf_counter()
                mx.synchronize()
            finished=time.perf_counter()
            response = {'id': request['id'], 'text': result['text'].strip()[:2000],
                        'timing':{'worker_input_ms':(converted-began)*1000,
                            'worker_transcribe_ms':(transcribed-converted)*1000,
                            'worker_final_sync_ms':(finished-transcribed)*1000,
                            'device_active_bytes':mx.get_active_memory(),'device_cache_bytes':mx.get_cache_memory(),
                            'stages':stages,'synchronized_profiling':args.profile_stages},
                        'confidence': {**segment_confidence(SimpleNamespace(**s) for s in result['segments']),
                                       'decoder': profile, 'prompt': None}}
        except Exception as error:
            response = {'id': request['id'], 'error': type(error).__name__}
        print(json.dumps(response), flush=True)


if __name__ == '__main__':
    main()
