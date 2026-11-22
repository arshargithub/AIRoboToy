"""Private stdin/stdout worker, no network, disk writes or playback."""
import argparse
import base64
import json
import sys
from contextlib import redirect_stdout

from .neural_voice import create_engine, generate, pcm_wave
from .speech_errors import SpeechWorkerError


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--backend',choices=('piper','kokoro-k','kokoro-k-mlx'),default='piper')
    backend=parser.parse_args().backend
    if backend=='kokoro-k-mlx':
        from .mlx_k import MLXK
        engine=MLXK();synthesize=engine.generate
    elif backend=='kokoro-k':
        from .kokoro_k import KokoroK
        engine=KokoroK()
        synthesize=engine.generate
    else:
        engine, config = create_engine('piper')
        synthesize=lambda text:generate(engine,config,text)
    # Warm the native paths before microphone capture starts. Synthetic only.
    synthesize('Hello. This is a local voice check.')
    print(json.dumps({'ready': True, 'protocol': 1}), flush=True)
    while line := sys.stdin.buffer.readline(8193):
        if len(line) > 8192 or not line.endswith(b'\n'):
            return
        request = json.loads(line)
        if (set(request) != {'id', 'text'} or not isinstance(request['id'], str)
                or len(request['id']) != 32 or not isinstance(request['text'],str)
                or not 0<len(request['text'])<=480):
            return
        try:
            # Library prints must never be interpreted as protocol responses.
            with redirect_stdout(sys.stderr):
                audio = synthesize(request['text'])
                data = pcm_wave(audio.samples, audio.sample_rate)
                if backend.startswith('kokoro-k'):
                    from .voice_audio import level_match
                    data,_=level_match(data)
            result={'id':request['id'],'wav':base64.b64encode(data).decode('ascii')}
        except Exception as error:
            # No exception messages, private reply text or raw phonemes on IPC.
            result={'id':request['id'],'error':getattr(error,'code','synthesis_failed')}
        print(json.dumps(result),flush=True)


if __name__ == '__main__': main()
