"""Offline saved-PCM Moonshine experiment; never opens microphone/speakers."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import time


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--mode',choices=('batch','stream'),default='batch')
    parser.add_argument('--paced',action='store_true');args=parser.parse_args()
    # Keep native/library stdout out of the framed protocol.
    protocol_fd=os.dup(sys.stdout.fileno());os.dup2(sys.stderr.fileno(),sys.stdout.fileno())
    def emit(value):
        data=memoryview((json.dumps(value,allow_nan=False)+'\n').encode())
        while data:data=data[os.write(protocol_fd,data):]
    def offline(*a,**kw):raise RuntimeError('Network disabled in saved-audio worker')
    socket.create_connection=offline
    socket.socket.connect=offline
    import numpy as np
    from moonshine_voice import ModelArch,Transcriber
    from importlib.metadata import version
    import moonshine_voice
    from .experiment_workflow import digest
    spec_path=Path('experiments/streaming-asr/model-manifest.json');spec=json.loads(spec_path.read_text())
    if version('moonshine-voice')!=spec['version']:raise ValueError('Unpinned streaming runtime')
    for info in spec['files']:
        path=Path(info['path'])
        if path.stat().st_size!=info['size'] or digest(path)!=info['sha256']:
            raise ValueError('Streaming model checksum changed')
    package=Path(moonshine_voice.__file__).parent
    for info in spec['runtime_files']:
        if digest(package/info['relative'])!=info['sha256']:raise ValueError('Streaming runtime checksum changed')
    root=Path(spec['files'][0]['path']).parent
    transcriber=Transcriber(model_path=root,model_arch=ModelArch.MEDIUM_STREAMING,update_interval=.5)
    profile={'model':spec['model'],'engine':'moonshine-voice','version':version('moonshine-voice'),
             'model_manifest_sha256':digest(spec_path),'prompt':None,'mode':args.mode,
             'paced':args.paced,'update_interval_seconds':.5,'native_options':'upstream defaults',
             'input':'local mono16k PCM16','network':'no downloader; Python socket connections disabled'}
    emit({'ready':True,'protocol':1,'profile':profile})
    try:
        for raw in sys.stdin.buffer:
            if len(raw)>900000:raise ValueError('Oversized worker request')
            request=json.loads(raw)
            try:
                pcm=base64.b64decode(request['pcm'],validate=True)
                if not 0<len(pcm)<=640000 or len(pcm)%2:raise ValueError('Invalid PCM bound')
                samples=np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768
                start=time.monotonic();events=[];calls=[];lag=[]
                if args.mode=='batch':
                    transcript=transcriber.transcribe_without_streaming(samples)
                    extra={}
                else:
                    stream=transcriber.create_stream();audio_position=0
                    def event(e):
                        if hasattr(e,'error'):raise e.error
                        events.append({'kind':type(e).__name__,'at_ms':(time.monotonic()-start)*1000,
                            'fed_samples':audio_position,'text_characters':len(e.line.text or ''),
                            'line_id':e.line.line_id,'is_complete':e.line.is_complete})
                    stream.add_listener(event)
                    try:
                        stream.start()
                        for offset in range(0,len(samples),1600):
                            chunk=samples[offset:offset+1600]
                            if args.paced:
                                due=start+(offset+len(chunk))/16000
                                time.sleep(max(0,due-time.monotonic()))
                                lag.append(max(0,(time.monotonic()-due)*1000))
                            audio_position=offset+len(chunk)
                            began=time.monotonic();stream.add_audio(chunk)
                            calls.append((time.monotonic()-began)*1000)
                        before_stop=time.monotonic();transcript=stream.stop()
                        if transcript is None:raise ValueError('Streaming stop did not return a transcript')
                        extra={'forced_stop_flush_ms':(time.monotonic()-before_stop)*1000,
                            'max_add_audio_ms':max(calls,default=0),'sum_add_audio_ms':sum(calls),
                            'max_pacing_lag_ms':max(lag,default=0),'stream_events':events,
                            'input_duration_ms':len(samples)/16}
                    finally:stream.close()
                elapsed=(time.monotonic()-start)*1000
                text=' '.join(line.text.strip() for line in transcript.lines).strip()[:2000]
                emit({'id':request['id'],'text':text,'confidence':{'schema_version':1,'segments':[],
                      'segment_count':0,'word_probabilities_available':False,'scores_available':False,
                      'interpretation':'This backend does not expose comparable Whisper decoder probabilities',
                      'decoder':profile,'prompt':None},
                      'timing':{'worker_transcribe_ms':elapsed,**extra}})
            except Exception as error:emit({'id':request['id'],'error':type(error).__name__})
    finally:transcriber.close()


if __name__=='__main__':main()
