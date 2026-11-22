"""Private offline model worker for the frozen ASR comparison; no playback."""
import argparse
from contextlib import redirect_stdout
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import resource
import sys
import time
from types import SimpleNamespace
import wave

os.environ.update(HF_HUB_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',HF_HUB_DISABLE_IMPLICIT_TOKEN='1',TRANSFORMERS_OFFLINE='1')


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--model',required=True)
    name=parser.parse_args().model
    initialized=time.perf_counter()
    import numpy as np
    from .asr_confidence import segment_confidence
    if name=='cpu_base.en':
        from faster_whisper import WhisperModel
        spec=json.loads(Path('tavi/web/speech-check-protocol.json').read_text())['models']['base.en']
        root=Path(spec['path'])
        for filename,sha in spec['files'].items():
            if digest(root/filename)!=sha:raise ValueError('CPU model hash mismatch')
        model=WhisperModel(str(root),device='cpu',compute_type='int8',cpu_threads=2,local_files_only=True)
        def transcribe(audio,prompt):
            segments,_=model.transcribe(audio,language='en',task='transcribe',beam_size=1,temperature=0,
                condition_on_previous_text=False,initial_prompt=prompt,vad_filter=False,word_timestamps=False)
            segments=list(segments)
            return {'text':' '.join(s.text for s in segments).strip(),'confidence':segment_confidence(segments)}
        profile={'engine':'faster-whisper','version':importlib.metadata.version('faster-whisper'),
                 'compute':'int8','cpu_threads':2,'model_sha256':spec['files']['model.bin']}
        mx=None
    else:
        import mlx.core as mx
        from mlx.utils import tree_flatten
        import mlx_whisper
        from mlx_whisper.transcribe import ModelHolder
        spec=next(m for m in json.loads(Path('tavi/asr_mlx_manifest.json').read_text())['models'] if m['id']==name)
        root=Path(spec['path'])
        for filename,info in spec['files'].items():
            if (root/filename).stat().st_size!=info['size'] or digest(root/filename)!=info['sha256']:
                raise ValueError('MLX model hash mismatch')
        mx.set_memory_limit(6*1024**3);mx.set_cache_limit(256*1024**2)
        with redirect_stdout(sys.stderr):model=ModelHolder.get_model(str(root),mx.float16)
        dtypes={}
        for _,array in tree_flatten(model.parameters()):
            key=str(array.dtype);row=dtypes.setdefault(key,{'arrays':0,'elements':0})
            row['arrays']+=1;row['elements']+=array.size
        def transcribe(audio,prompt):
            result=mlx_whisper.transcribe(audio,path_or_hf_repo=str(root),verbose=None,language='en',task='transcribe',
                temperature=0,condition_on_previous_text=False,initial_prompt=prompt,word_timestamps=False,fp16=True)
            mx.synchronize()
            return {'text':result['text'].strip(),
                    'confidence':segment_confidence(SimpleNamespace(**s) for s in result['segments'])}
        profile={'engine':'mlx-whisper','version':importlib.metadata.version('mlx-whisper'),
                 'mlx_version':importlib.metadata.version('mlx'),'compute':'float16','parameter_dtypes':dtypes,
                 'revision':spec['revision'],'model_files':spec['files'],
                 'greedy':'beam_size omitted because this MLX implementation does not implement beam search'}
    print(json.dumps({'ready':True,'profile':profile,'initialization_ms':(time.perf_counter()-initialized)*1000}),flush=True)
    for line in sys.stdin.buffer:
        request=json.loads(line)
        try:
            with wave.open(request['wav']) as wav:
                if (wav.getframerate(),wav.getnchannels(),wav.getsampwidth())!=(16000,1,2):raise ValueError('Invalid PCM')
                if not 0<wav.getnframes()<=320000:raise ValueError('Invalid input duration')
                pcm=wav.readframes(wav.getnframes())
            audio=np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768
            if mx:mx.reset_peak_memory()
            began=time.perf_counter()
            with redirect_stdout(sys.stderr):result=transcribe(audio,request['prompt'])
            result.update(id=request['id'],decode_ms=(time.perf_counter()-began)*1000,
                          peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                          device_peak_bytes=mx.get_peak_memory() if mx else None,
                          device_active_bytes=mx.get_active_memory() if mx else None)
        except Exception as error:
            result={'id':request['id'],'error':type(error).__name__}
        print(json.dumps(result),flush=True)


if __name__=='__main__':main()
