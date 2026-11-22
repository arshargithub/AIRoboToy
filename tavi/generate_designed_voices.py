"""Bounded, fully offline voice-description experiment in the isolated MLX lab.

No reference speaker audio, microphone, celebrity name, provider key or remote
inference is used. Only the two fixed synthetic audition texts are generated.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import signal
import time

os.environ['HF_HUB_OFFLINE']='1'
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'

from .neural_voice import pcm_wave
from .prepare_voice_audition import PASSAGES
from .voice_pronunciation import DESIGN_INSTRUCTION, PRONUNCIATION, IPA

ROOT=Path('.tavi/voice-direction')
MODEL=Path('.tavi/models/qwen3-voice-design-4bit')
PROMPTS={
 'L': 'A young adult woman in her early twenties speaking natural American English. Her voice is youthful, warm and naturally a little husky, with a light organic rasp in her tone. She has a grounded low-to-mid register and clear confident presence. Her delivery is relaxed, friendly, playful and conversational.',
 'M': 'A youthful adult female voice speaking American English with a naturally slightly raspy, textured timbre and a warm resonant core. She sounds confident and lively, with easy conversational energy, natural rhythm and expressive intonation. The light huskiness is part of her normal speaking voice.',
}
HUSKY_PROMPTS={
 'N': 'An adult woman speaking American English in a naturally low contralto register. Her speaking voice is chest-resonant, dry and distinctly husky, with audible grain and a gentle coarse rasp throughout ordinary speech. She has a relaxed, grounded, confident delivery, with restrained pitch movement and a warm full-bodied tone. Clear normal-volume conversational speech, close and intimate, with occasional light vocal fry at phrase endings.',
 'O': 'A woman in her late twenties with a naturally gravelly, smoky speaking voice and a low-to-medium female register. Her vocal timbre has obvious rough texture, a soft hoarse edge and chest resonance. She speaks American English with casual confident presence, unhurried natural rhythm and understated dry humor. The rasp is audible in the voiced vowels while her words stay clear and conversational.',
}


def timeout(signum,frame):
    raise TimeoutError('Voice-design generation exceeded its 180-second per-clip bound')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--husky',action='store_true',help='New lower-register N/O experiment; preserve earlier voices')
    husky=parser.parse_args().husky
    root=Path('.tavi/voice-husky') if husky else ROOT
    prompts=HUSKY_PROMPTS if husky else PROMPTS
    import numpy as np
    import mlx.core as mx
    from mlx_audio.tts.utils import load_model
    root.mkdir(exist_ok=True,parents=True)
    manifest=json.loads((MODEL/'download-manifest.json').read_text())
    for file in manifest['files']:
        path=MODEL/file['path']
        if path.stat().st_size!=file['size'] or hashlib.sha256(path.read_bytes()).hexdigest()!=file['sha256']:
            raise ValueError('Voice-design weight changed: '+file['path'])
    mx.set_memory_limit(6*1024**3);mx.set_cache_limit(256*1024**2)
    signal.signal(signal.SIGALRM,timeout)
    start=time.perf_counter();model=load_model(MODEL,lazy=False,strict=True)
    if model.config.tts_model_type!='voice_design' or model.speech_tokenizer is None or model.tokenizer is None:
        raise ValueError('Voice design model failed local initialization')
    print(f'Local voice-design model loaded in {time.perf_counter()-start:.1f}s',flush=True)
    settings={'memory_limit_bytes':6*1024**3,'cache_limit_bytes':256*1024**2,
              'max_tokens':350,'temperature':.7,'top_k':50,'top_p':.95,
              'repetition_penalty':1.05,'per_clip_timeout_seconds':180,
              'library_versions':{name:importlib.metadata.version(name) for name in ('mlx-audio','mlx','transformers','numpy')}}
    report={'model':{'repository':manifest['repository'],'revision':manifest['revision'],
                    'manifest_sha256':hashlib.sha256((MODEL/'download-manifest.json').read_bytes()).hexdigest(),
                    'license':'Apache-2.0'},'settings':settings,'trials':[],
            'api_spend_usd':0,'scope':'Natural-language voice design; fully local fixed synthetic text, no reference audio or playback.'}
    previous=json.loads((root/'design.json').read_text()) if (root/'design.json').exists() else None
    for voice,instruction in prompts.items():
        for case,text in PASSAGES.items():
            retained=next((row for row in previous['trials'] if row['voice']==voice and row['case']==case),None) if previous else None
            if case=='short_story' and retained:
                row=retained
                if hashlib.sha256(Path(row['wav']).read_bytes()).hexdigest()!=row['sha256']:
                    raise ValueError('Retained designed story changed')
                report['trials'].append(row)
                continue
            effective_instruction=instruction+' '+DESIGN_INSTRUCTION if case=='greeting' else instruction
            seed={'L':43,'M':71,'N':97,'O':127}[voice];mx.random.seed(seed);mx.reset_peak_memory()
            start=time.perf_counter();signal.alarm(180)
            try:
                outputs=list(model.generate_voice_design(text=text,instruct=effective_instruction,language='English',
                    temperature=.7,max_tokens=350,top_k=50,top_p=.95,repetition_penalty=1.05,verbose=False,stream=False))
                if len(outputs)!=1 or outputs[0].token_count>=350:
                    raise ValueError('Voice-design output missing, segmented or hit its token bound')
                result=outputs[0];samples=np.array(result.audio,dtype=np.float32)
                data=pcm_wave(samples,result.sample_rate)
            finally:signal.alarm(0)
            suffix='-pronunciation-v1' if case=='greeting' else ''
            path=root/f'design-{voice.lower()}-{case}{suffix}.wav';path.write_bytes(data)
            row={'voice':voice,'case':case,'text':text,'instruction':effective_instruction,'seed':seed,
                 'pronunciation_target':PRONUNCIATION if case=='greeting' else None,
                 'pronunciation_ipa':IPA if case=='greeting' else None,
                 'wav':str(path),'sha256':hashlib.sha256(data).hexdigest(),
                 'preparation_ms':(time.perf_counter()-start)*1000,
                 'duration_ms':len(samples)*1000/result.sample_rate,'tokens':result.token_count,
                 'peak_memory_bytes':mx.get_peak_memory()}
            report['trials'].append(row);(root/'design.json').write_text(json.dumps(report,indent=2)+'\n')
            print(f'{voice} {case}: {row["preparation_ms"]/1000:.1f}s preparation, {row["duration_ms"]/1000:.1f}s audio, {row["tokens"]} tokens',flush=True)
            mx.clear_cache()
    print('Four designed samples saved locally. Vocal character, consistency and live latency still require evaluation.',flush=True)


if __name__=='__main__':main()
