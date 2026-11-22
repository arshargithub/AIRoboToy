"""Explicit fresh-adult ASR comparison, isolated from live conversation services."""
import argparse
import asyncio
import base64
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path
import re
import secrets
import signal
import tempfile
import threading
import time
import wave

from .cloud_transcription import CloudTranscription
from .mlx_final_asr import MlxFinalASR
from .experiment_workflow import begin,finish
from .storage import Store

PHRASES=[
 'Paprika, could we make a bridge for two toy cars?',
 'Please give the tiny robot a blue hat and a silver backpack.',
 'Wait, change it to a jungle story with a friendly crocodile.',
 'That is all for now, Paprika. See you later.']
PROTOCOL={'id':'paprika-fresh-adult-asr-v1','phrases':PHRASES,'frames_per_clip':250,
    'sample_rate':16000,'purpose':'Fresh recorded-speech recognition comparison, not voice preference or full conversation/wake/interruption acceptance.',
    'local_model':'MLX unhinted turbo control','cloud_model':'gpt-transcribe',
    'cloud_scope':'Only these new explicitly consented adult test clips. Existing recordings are never imported. No child data.'}
PROTOCOL_HASH=hashlib.sha256(json.dumps(PROTOCOL,sort_keys=True).encode()).hexdigest()


def decode_pcm(encoded):
    pcm=base64.b64decode(encoded,validate=True)
    if len(pcm)!=256000:raise ValueError('Expected exactly eight seconds of complete16k PCM16')
    return pcm


class ReviewLab:
    def __init__(self,store,decoder=None,cloud_factory=None,data_root=None,record_workflow=True):
        self.store=store;self.decoder=decoder or MlxFinalASR()
        self.cloud_factory=cloud_factory or (lambda:CloudTranscription(store))
        self.data_root=Path(data_root or '.tavi/private-asr-comparisons')
        self.sessions={};self.active=None;self.serial=asyncio.Lock()
        self.record_workflow=record_workflow

    async def prepare(self,body):
        if body.get('adult') is not True or body.get('recording_consent') is not True:
            raise ValueError('Confirm adult participation and new test recording first')
        cloud=body.get('cloud')
        if type(cloud) is not bool:raise ValueError('Choose whether these new clips may go to OpenAI')
        if self.active:await self.stop({'session_id':self.active})
        if len(self.sessions)>=8:raise ValueError('Test session limit reached; save results and restart this lab')
        key=body.get('session_id','')
        if not isinstance(key,str) or not re.fullmatch(r'[a-f0-9]{32}',key) or key in self.sessions:
            raise ValueError('A fresh test identifier is required')
        s={'cloud':cloud,'stopped':False,'results':{},'created':time.monotonic(),'task':None,
           'provider':None,'mapping':{'A':'local','B':'cloud'} if secrets.randbits(1) else {'A':'cloud','B':'local'}}
        if not cloud:s['mapping']={'A':'local'}
        if self.record_workflow:
            folder,_=begin('experiments/streaming-asr/fresh-adult-protocol-v1.json',
                consent={'adult':True,'recording':True,'cloud':cloud})
            s['workflow']=folder
            (folder/'choices.json').write_text(json.dumps({'cloud':cloud,'mapping':s['mapping'],
                'protocol_sha256':PROTOCOL_HASH,'adult':True,'recording_consent':True},indent=2)+'\n')
        self.sessions[key]=s;self.active=key
        try:
            async with self.serial:
                await asyncio.to_thread(self.decoder.prepare)
                if cloud:s['provider']=self.cloud_factory()
            if s['stopped']:raise ValueError('Preparation cancelled')
        except BaseException:
            s['stopped']=True
            if s['provider']:await s['provider'].close();s['provider']=None
            raise
        return {'session_id':key,'ready':True,'cloud':cloud,'protocol':PROTOCOL,'protocol_sha256':PROTOCOL_HASH}

    def session(self,body):
        key=body.get('session_id');s=self.sessions.get(key)
        if not s:raise ValueError('Test session expired; start a new test')
        return s

    async def compare(self,body):
        s=self.session(body)
        index=body.get('index')
        if type(index) is not int or not 0<=index<4:raise ValueError('Unexpected test turn')
        pcm=decode_pcm(body.get('pcm',''));pcm_sha=hashlib.sha256(pcm).hexdigest()
        if index in s['results']:
            if s['results'][index]['pcm_sha256']!=pcm_sha:raise ValueError('Completed test input cannot be replaced')
            return s['results'][index]  # Lost HTTP response may be recovered without another paid request.
        if s['stopped'] or time.monotonic()-s['created']>1800:raise ValueError('Test stopped or expired')
        if index!=len(s['results']):raise ValueError('Unexpected test order')
        if s['task']:raise ValueError('A comparison is already running')
        s['task']=asyncio.current_task();rows={}
        try:
            async with self.serial:
                began=time.monotonic()
                try:
                    value=await asyncio.to_thread(self.decoder.decode,pcm,began+15,lambda:not s['stopped'])
                    rows['local']={'text':value.text,'elapsed_ms':(time.monotonic()-began)*1000,
                                   'profile':self.decoder.profile,'confidence':value.confidence,'timing':value.timing}
                except Exception as error:
                    rows['local']={'error':type(error).__name__}
                if s['stopped']:raise asyncio.CancelledError()
                if s['cloud']:
                    buffer=BytesIO()
                    with wave.open(buffer,'wb') as wav:
                        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(pcm)
                    try:
                        rows['cloud']=await s['provider'].transcribe(buffer.getvalue(),source_kind='new_adult_test',consent=True)
                    except Exception as error:
                        rows['cloud']={'error':type(error).__name__}
            if s['stopped']:raise asyncio.CancelledError()
            result={'index':index,'pcm_sha256':pcm_sha,'candidates':{k:rows[v] for k,v in s['mapping'].items()}}
            s['results'][index]=result
            return result
        finally:s['task']=None

    async def stop(self,body):
        s=self.session(body);s['stopped']=True
        task=s['task']
        if task and task is not asyncio.current_task():
            self.decoder.cancel();task.cancel()
        return {'stopped':True,'completed_clips':len(s['results'])}

    async def save(self,body):
        s=self.session(body)
        if not s['stopped'] or s['task']:raise ValueError('Stop capture/comparison before saving')
        reviews=body.get('reviews');clips=body.get('clips');include=body.get('include_audio')
        if not isinstance(reviews,list) or not isinstance(clips,list) or type(include) is not bool:
            raise ValueError('Invalid review/save choice')
        if len(clips)!=len(s['results']) or not clips:raise ValueError('No matching completed clips to save')
        if len(reviews)!=len(clips):raise ValueError('Missing per-clip review')
        saved_clips=[]
        for index,(clip,review) in enumerate(zip(clips,reviews)):
            if clip.get('index')!=index or not isinstance(review,dict):raise ValueError('Review order mismatch')
            for letter in s['mapping']:
                if review.get(letter) not in ('correct','wrong','unsure',None):raise ValueError('Invalid review label')
            pcm=decode_pcm(clip.get('pcm',''))
            if hashlib.sha256(pcm).hexdigest()!=s['results'][index]['pcm_sha256']:raise ValueError('Recording differs from compared input')
            record={'index':index,'settings':{k:v for k,v in clip.get('settings',{}).items() if k in
                ('sampleRate','channelCount','echoCancellation','noiseSuppression','autoGainControl','voiceIsolation')}}
            if include:record['pcm_base64']=clip['pcm']
            saved_clips.append(record)
        result={'schema_version':1,'kind':'paprika_fresh_adult_asr_comparison','protocol':PROTOCOL,
                'protocol_sha256':PROTOCOL_HASH,'adult_consent':True,'new_recording_consent':True,
                'cloud_new_clips_consent':s['cloud'],'mapping':s['mapping'],
                'results':list(s['results'].values()),'reviews':reviews,'clips':saved_clips,
                'include_audio':include,'spent_or_reserved_usd':self.store.used_micro_usd()/1e6,
                'interpretation':'Human word labels and complete-file processing timing only; no automatic product pass.'}
        raw=json.dumps(result,sort_keys=True).encode();sha=hashlib.sha256(raw).hexdigest()
        self.data_root.mkdir(parents=True,exist_ok=True,mode=0o700)
        existing=list(self.data_root.glob('*.json'))
        if sum(p.stat().st_size for p in existing)+len(raw)>64_000_000:raise ValueError('Local results folder full; existing data preserved')
        path=self.data_root/(sha+'.json')
        if path.exists():
            if path.read_bytes()!=raw:raise ValueError('Existing result failed integrity check; original preserved')
        else:
            temporary=None
            try:
                with tempfile.NamedTemporaryFile(dir=self.data_root,prefix='.saving-',delete=False) as output:
                    temporary=output.name;os.chmod(temporary,0o600)
                    output.write(raw);output.flush();os.fsync(output.fileno())
                try:os.link(temporary,path)  # Atomic publication without overwriting an existing result.
                except FileExistsError:
                    if path.read_bytes()!=raw:raise ValueError('Result collision; original preserved')
            finally:
                if temporary:os.unlink(temporary)
        if s.get('workflow') and not s.get('workflow_finished'):
            metrics={'completed_turns':len(clips),
                'all_results_reviewed':True if all(review.get(k) is not None for review in reviews for k in s['mapping']) else None}
            finish(s['workflow'],metrics,artifacts=[path,s['workflow']/'choices.json'])
            s['workflow_finished']=True
        return {'saved':True,'id':sha,'completed_clips':len(clips),'include_audio':include,'mapping':s['mapping']}

    async def close(self):
        for key,s in self.sessions.items():
            await self.stop({'session_id':key})
            if s['provider']:await s['provider'].close()
        await asyncio.to_thread(self.decoder.close)


def handler(lab,loop,port):
    root=Path(__file__).with_name('web');allowed={f'http://127.0.0.1:{port}',f'http://localhost:{port}'}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,status,body,kind='application/json'):
            if not isinstance(body,bytes):body=json.dumps(body).encode()
            self.send_response(status);self.send_header('Content-Type',kind)
            self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; media-src 'self' blob:; object-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            try:self.wfile.write(body)
            except (BrokenPipeError,ConnectionResetError):pass
        def valid(self):return 'http://'+self.headers.get('Host','') in allowed
        def do_GET(self):
            if not self.valid():return self.reply(403,{'error':'Localhost only'})
            assets={'/':('asr-review.html','text/html; charset=utf-8'),'/asr-review.js':('asr-review.js','text/javascript'),
                '/sample-collector.js':('sample-collector.js','text/javascript'),'/capture.js':('capture.js','text/javascript')}
            if self.path=='/protocol':return self.reply(200,{**PROTOCOL,'sha256':PROTOCOL_HASH})
            if self.path not in assets:return self.reply(404,{'error':'Not found'})
            file,kind=assets[self.path];return self.reply(200,(root/file).read_bytes(),kind)
        def do_POST(self):
            if not self.valid() or self.headers.get('Origin') not in allowed:
                return self.reply(403,{'error':'Same-origin test action required'})
            actions={'/prepare':lab.prepare,'/compare':lab.compare,'/stop':lab.stop,'/save':lab.save}
            if self.path not in actions:return self.reply(404,{'error':'Not found'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=2_000_000:raise ValueError('Invalid request size')
                body=json.loads(self.rfile.read(size))
                if not isinstance(body,dict):raise ValueError('Expected test object')
                future=asyncio.run_coroutine_threadsafe(actions[self.path](body),loop)
                result=future.result(timeout=45 if self.path in ('/prepare','/compare') else 5)
                return self.reply(200,result)
            except TimeoutError:
                future.cancel();return self.reply(503,{'error':'Test processing timed out. Stop and save completed clips.'})
            except Exception as error:
                message=str(error) if isinstance(error,ValueError) else 'Test action failed; stop and save completed clips.'
                return self.reply(400,{'error':message})
    return Handler


async def serve(port):
    store=Store('.tavi/simulation/simulation.sqlite3');lab=ReviewLab(store)
    loop=asyncio.get_running_loop();server=ThreadingHTTPServer(('127.0.0.1',port),handler(lab,loop,port))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();done=asyncio.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):loop.add_signal_handler(sig,done.set)
    print(f'Fresh adult comparison: http://127.0.0.1:{port}/ · microphone off',flush=True)
    try:await done.wait()
    finally:
        await asyncio.to_thread(server.shutdown);server.server_close();await lab.close();store.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8767)
    asyncio.run(serve(parser.parse_args().port))
