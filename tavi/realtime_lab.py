"""Isolated adult-only native reference with local VAD and bounded cloud engagement.

All actions stay on one asyncio loop. Existing no-upload recordings have no
import route. The normal Paprika conversation controller is untouched.
"""
import asyncio
import audioop
import base64
from collections import deque
import hashlib
import importlib.metadata
import sys
import json
import os
from pathlib import Path
import re
import time
from uuid import uuid4

from .acoustics import Silero
from .experiment_workflow import begin, finish, ROOT
from .realtime_reference import RealtimeReference, RESERVATION, charge_usage
from .storage import APPROVED_BUDGET_MICRO_USD

PROTOCOL_PATH = 'experiments/realtime/adult-protocol-v1.json'
CLOSURE_PROTOCOL_PATH = 'experiments/realtime/adult-closure-protocol-v2.json'
CLOSURE_RATING_KEYS = ('quiet_complete','goodbye','no_reintroduction','responsive')
RATING_KEYS = ('quiet_complete', 'followup', 'stopped_promptly', 'changed_story', 'goodbye', 'responsive', 'voice_acceptable')


class NativeSession:
    def __init__(self, store, session_id, *, detector=None, provider=None, maximum_requests=5):
        if type(maximum_requests) is not int or not 1<=maximum_requests<=5:raise ValueError("Invalid request bound")
        self.maximum_requests=maximum_requests
        self.store, self.id = store, session_id
        self.detector = detector
        self.provider = provider or RealtimeReference(store)
        self.sequence = -1
        self.pre = deque(maxlen=10)
        self.high = self.quiet = self.speech_frames = 0
        self.in_speech = False
        self.utterance_frames = 0
        self.rate_state = None
        self.microphone_digest = hashlib.sha256()
        self.input_digest = None
        self.input_bytes = 0
        self.rows, self.out, self.trace, self.recording = [], deque(), [], bytearray()
        self.current = self.pending = None
        self.started = self.last_frame = time.monotonic()
        self.stopped = False
        self.armed = False
        self.error = None
        self.reader = None
        self.folder = None
        self.capture_audio = False
        self.reserved_calls = 0
        self.initial_spend = store.used_micro_usd()
        self.lock = asyncio.Lock()
        self.saved = None
        self.last_speech_sample = 0
        self.stop_lock = asyncio.Lock()

    async def prepare(self, body, *, record_workflow=True):
        if body.get('adult') is not True or body.get('cloud') is not True or body.get('recording') is not True:
            raise ValueError('Explicit adult, new cloud speech and transient capture agreement required')
        if type(body.get('save_audio')) is not bool: raise ValueError('Choose whether local microphone audio may be saved')
        self.capture_audio = body['save_audio']
        self.workflow = body.get('workflow','full-v1')
        protocol_path, self.rating_keys, self.maximum_requests = self.workflow_spec(self.workflow)
        if record_workflow:
            self.folder, _ = begin(protocol_path, consent={'adult':True,'recording':True,'cloud':True})
        self.choices = {'adult':True,'recording':True,'cloud':True,'save_audio':self.capture_audio,'workflow':self.workflow}
        self.runtime = {'python':sys.version}
        for name in ('openai','websockets','numpy','onnxruntime'):
            try:self.runtime[name]=importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:self.runtime[name]=None
        if self.detector is None:
            self.detector = Silero(ROOT/'.tavi/models/silero_vad.onnx', wake_backend='off')
        await self.prepare_provider()
        self.started = self.last_frame = time.monotonic()
        return {'ready':True, 'session_id':self.id, 'maximum_seconds':180, 'volume':0.35}

    def workflow_spec(self, workflow):
        if workflow=='closure-v2':return CLOSURE_PROTOCOL_PATH, CLOSURE_RATING_KEYS, 2
        if workflow=='full-v1':return PROTOCOL_PATH, RATING_KEYS, self.maximum_requests
        raise ValueError('Unknown guided workflow')

    async def prepare_provider(self):
        await self.provider.connect()
        self.reader = asyncio.create_task(self.read())

    def note(self, kind, **data):
        if len(self.trace) >= 600: raise ValueError('Trace limit exceeded')
        self.trace.append({'kind':kind, 'ms':(time.monotonic()-self.started)*1000, **data})

    async def read(self):
        try:
            while not self.stopped:
                e = await self.provider.receive()
                kind = e['type']
                if kind == 'response.created':
                    if not self.pending: raise ValueError('Unexpected native response')
                    self.current = self.pending; self.pending = None
                    self.current.update(response_id=e['response']['id'], done=False, blocked=False, played=False, frames=0)
                    self.rows.append(self.current)
                elif kind == 'response.output_item.added':
                    if not self.current: raise ValueError('Assistant item without response')
                    self.current['item_id'] = e['item']['id']
                elif kind == 'response.output_audio.delta':
                    row = self.current
                    if not row or e.get('response_id') != row['response_id'] or e.get('item_id') != row.get('item_id'):
                        raise ValueError('Unbound native audio')
                    pcm = base64.b64decode(e['delta'], validate=True)
                    if len(pcm)%2 or row['frames']+len(pcm)//2 > 30*24000:
                        raise ValueError('Native audio limit exceeded')
                    row['frames'] += len(pcm)//2
                    row.setdefault('first_audio_after_commit_ms',(time.monotonic()-row['commit_monotonic'])*1000)
                    if not row['blocked']:
                        if len(self.out)>160: raise ValueError('Native output backlog exceeded')
                        self.out.append({'kind':'audio','id':row['response_id'],'item_id':row['item_id'],'pcm':e['delta'],
                                         'speech_end_sample':row['speech_end_sample']})
                elif kind == 'response.output_audio_transcript.delta':
                    if not self.current: raise ValueError('Transcript without response')
                    row = self.current
                    row['text'] = row.get('text','') + e['delta']
                    if len(row['text'])>5000: raise ValueError('Native transcript limit exceeded')
                elif kind == 'response.done':
                    row = self.current; response = e['response']
                    if not row or response.get('id') != row['response_id'] or row['done']:
                        raise ValueError('Unbound native completion')
                    row.update(done=True,status=response['status'],usage=response.get('usage'))
                    charge = charge_usage(row['usage'])
                    row['usage_settled'] = charge is not None
                    if charge is not None: self.store.settle(row['reservation_id'],charge)
                    if row['status'] not in ('completed','cancelled'):
                        raise ValueError('Native reply did not complete')
                    self.out.append({'kind':'done','id':row['response_id'],'status':row['status']})
                    self.note('response_terminal', id=row['response_id'],status=row['status'])
                elif kind == 'conversation.item.truncated':
                    row = next((r for r in self.rows if r.get('item_id')==e.get('item_id')),None)
                    if not row or e.get('audio_end_ms')!=row.get('truncated_ms'):
                        raise ValueError('Native truncation mismatch')
                    row['truncated_ack'] = True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self.stopped:
                self.error = str(exc)[:150] if isinstance(exc,ValueError) else 'Native connection failed'
                self.note('provider_failure',error=self.error)
            # Watchdog closes transport promptly; no retry or further input.

    def row_for(self, response_id):
        return next((r for r in self.rows if r.get('response_id')==response_id),None)

    async def frame(self, body):
        async with self.lock:
            if self.stopped or self.error: raise ValueError(self.error or 'Test stopped; save your results')
            now = time.monotonic()
            sequence = body.get('sequence')
            if type(sequence) is not int or not 0<=sequence<5625 or sequence != self.sequence+1 or (self.armed and now-self.last_frame>2):
                raise ValueError('Microphone stream lost its place; stop and save this attempt')
            if now-self.started>180: raise ValueError('Three-minute test limit reached')
            pcm = base64.b64decode(body.get('pcm',''),validate=True)
            if len(pcm)!=1024: raise ValueError('Invalid microphone frame')
            self.sequence=sequence;self.last_frame=now;self.armed=True
            self.microphone_digest.update(pcm)
            if self.capture_audio:self.recording.extend(pcm)
            probability = self.detector.probability(pcm)
            self.pre.append(pcm)
            self.high = self.high+1 if probability>=.65 else 0
            events = []
            if not self.in_speech and self.high>=2:
                if self.reserved_calls>=self.maximum_requests or self.store.used_micro_usd()+RESERVATION-self.initial_spend>self.maximum_requests*RESERVATION:
                    raise ValueError('This test reached its request limit; stop and save')
                if self.pending or self.current and not self.current['done'] and not self.current.get('item_id'):
                    raise ValueError('Another reply is still starting; stop and save')
                self.begin_input()
                self.in_speech=True;self.quiet=0;self.speech_frames=0;self.utterance_frames=0
                for data in self.pre:await self.append(data)
                self.note('speech_started',sequence=sequence)
                events.append({'kind':'speech_started'})
            elif self.in_speech:
                await self.append(pcm)
            if self.in_speech:
                self.utterance_frames+=1
                if probability>=.5:
                    self.quiet=0;self.speech_frames+=1;self.last_speech_sample=(sequence+1)*512
                else:self.quiet+=1
                if self.utterance_frames>375:raise ValueError('That turn was too long; stop and save')
                if self.quiet>=18:
                    if self.speech_frames<6:
                        # No generation; transmitted input leaves the conservative
                        # reservation unresolved. Unknown billing is never zeroed.
                        await self.provider.send('input_audio_buffer.clear')
                        self.note('short_sound_rejected',speech_frames=self.speech_frames)
                    else:
                        await self.commit_input()
                        self.note('input_committed',speech_end_sample=self.last_speech_sample)
                        events.append({'kind':'committed','speech_end_sample':self.last_speech_sample})
                    self.in_speech=False;self.high=0;self.pre.clear()
            result={'probability':probability,'events':events+list(self.out),'rows':len(self.rows)}
            self.out.clear()
            return result

    def begin_input(self):
        if self.reserved_calls>=self.maximum_requests or self.store.used_micro_usd()+RESERVATION-self.initial_spend>self.maximum_requests*RESERVATION:
            raise ValueError('This test reached its request limit; stop and save')
        reservation='native-adult:'+self.id+':'+str(self.reserved_calls)
        self.store.reserve(reservation,RESERVATION,APPROVED_BUDGET_MICRO_USD)
        self.reserved_calls+=1;self.reservation=reservation
        self.rate_state=None;self.input_digest=hashlib.sha256();self.input_bytes=0

    def response_options(self):
        return {}

    async def commit_input(self):
        row=self.current
        if self.pending:raise ValueError('Another reply is still starting; stop and save')
        if row and not row.get('played') and not row.get('blocked'):
            raise ValueError('Speech overlapped a reply without a confirmed local stop; save this attempt')
        deadline=time.monotonic()+2
        while row and row.get('blocked') and (not row['done'] or not row.get('truncated_ack')):
            if self.error or time.monotonic()>deadline:raise ValueError('Interruption did not synchronize; stop and save')
            await asyncio.sleep(.01)
        self.pending={'reservation_id':self.reservation,'speech_end_sample':self.last_speech_sample,
                      'commit_monotonic':time.monotonic(),'text':'',
                      'input_pcm24_sha256':self.input_digest.hexdigest(),'input_pcm24_bytes':self.input_bytes}
        options=self.response_options()
        await self.provider.send('input_audio_buffer.commit')
        await self.provider.send('response.create',**options)

    def record_extras(self):
        return {}

    async def append(self, pcm):
        converted,self.rate_state=audioop.ratecv(pcm,2,1,16000,24000,self.rate_state)
        self.input_digest.update(converted);self.input_bytes+=len(converted)
        await self.provider.send('input_audio_buffer.append',audio=base64.b64encode(converted).decode())

    async def interrupt(self, body):
        row=self.row_for(body.get('id'));ms=body.get('played_ms')
        if not row or type(ms) is not int or not 0<=ms<=row['frames']*1000//24000:
            raise ValueError('Invalid played-audio boundary')
        if row.get('blocked'):return {'stopped':True}
        row['blocked']=True;row['truncated_ms']=ms;self.out=deque(e for e in self.out if e.get('id')!=row['response_id'])
        if not row['done']:await self.provider.send('response.cancel',response_id=row['response_id'])
        await self.provider.send('conversation.item.truncate',item_id=row['item_id'],content_index=0,audio_end_ms=ms)
        self.note('local_stop_reported',id=row['response_id'],played_ms=ms)
        return {'stopped':True}

    async def played(self, body):
        row=self.row_for(body.get('id'))
        if not row or not row['done'] or row.get('blocked'):raise ValueError('Reply not fully playable')
        row['played']=True
        row['browser_estimated_latency_ms']=body.get('latency_ms') if isinstance(body.get('latency_ms'),(int,float)) and 0<=body['latency_ms']<=60000 else None
        self.note('playback_completed',id=row['response_id'])
        return {'played':True}

    async def stop(self):
        async with self.stop_lock:
            if self.stopped:return {'stopped':True}
            row=self.current
            if row and not row['done']:
                row['blocked']=True
                try:
                    await self.provider.send('response.cancel',response_id=row['response_id'])
                    deadline=time.monotonic()+1
                    while not row['done'] and time.monotonic()<deadline:await asyncio.sleep(.01)
                except Exception:pass
            self.stopped=True
            await self.provider.close()
            if self.reader:
                self.reader.cancel();await asyncio.gather(self.reader,return_exceptions=True)
            self.out.clear();self.pre.clear();self.note('test_stopped')
            return {'stopped':True}

    async def save(self, body, *, data_root=None):
        if not self.stopped:raise ValueError('Stop the microphone and test before saving')
        if self.saved:return self.saved
        ratings=body.get('ratings',{})
        if not isinstance(ratings,dict) or set(ratings)-set(self.rating_keys) or any(v not in ('yes','no','unsure',None) for v in ratings.values()):
            raise ValueError('Invalid review choice')
        note=body.get('note','')
        if not isinstance(note,str) or len(note)>1000:raise ValueError('Keep your note under1000 characters')
        trace=body.get('playback_trace',[])
        if not isinstance(trace,list) or len(json.dumps(trace))>50000:raise ValueError('Playback trace limit exceeded')
        record={'kind':'paprika_adult_native_reference','schema_version':1,'session_id':self.id,'choices':self.choices,
                'runtime':self.runtime,'microphone_pcm16_sha256':self.microphone_digest.hexdigest(),
                'session_configuration':{k:getattr(self.provider,'session',{}).get(k) for k in ('model','audio','reasoning','max_output_tokens','output_modalities','truncation')} if getattr(self.provider,'session',None) else None,
                'rows':self.rows,'trace':self.trace,'playback_trace':trace,'ratings':{k:ratings.get(k) for k in self.rating_keys},
                'note':note,'error':self.error,'frames_received':self.sequence+1,
                'spent_reserved_usd':self.store.used_micro_usd()/1e6,'include_audio':self.capture_audio,
                'interpretation':'Adult exploratory reference; browser latency estimates and human task ratings. No acoustic p95, wake, child/family or production acceptance.'}
        record.update(self.record_extras())
        if self.capture_audio:record['pcm16_16000_base64']=base64.b64encode(self.recording).decode()
        raw=json.dumps(record,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
        root=Path(data_root) if data_root else ROOT/'.tavi/private-native-references'
        root.mkdir(mode=0o700,parents=True,exist_ok=True)
        if sum(p.stat().st_size for p in root.glob('*.json'))+len(raw)>64_000_000:raise ValueError('Private results folder full; original results preserved')
        digest=hashlib.sha256(raw).hexdigest();path=root/(digest+'.json')
        temporary=root/('.'+self.id+'.'+uuid4().hex+'.tmp')
        created=False
        try:
            fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            created=True
            with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
            try:os.link(temporary,path)
            except FileExistsError:
                if path.read_bytes()!=raw:raise ValueError('Saved result integrity mismatch')
        finally:
            if created and temporary.exists():temporary.unlink()
        if self.folder:
            finish(self.folder,{'saved':True,'all_reviewed':all(record['ratings'][k] is not None for k in self.rating_keys)},
                   artifacts=[path],completed=True)
        self.saved={'saved':True,'file':path.name,'spent_reserved_usd':record['spent_reserved_usd']}
        return self.saved


class NativeLab:
    def __init__(self, store):self.store=store;self.sessions={};self.prepare_lock=asyncio.Lock()
    async def action(self, path, body):
        token=body.get('session_id')
        if not isinstance(token,str) or not re.fullmatch('[a-f0-9]{32}',token):raise ValueError('Invalid test identifier')
        if path=='/readiness':
            from .parent_readiness import save_readiness
            return save_readiness(body)
        if path=='/prepare':
            async with self.prepare_lock:
                if token in self.sessions:raise ValueError('This attempt already exists; stop and save it')
                if len(self.sessions)>=8 or any(not s.stopped for s in self.sessions.values()):raise ValueError('Another test is active; stop it first')
                if body.get('workflow')=='engagement-v1':
                    from .engaged_native import EngagedNativeSession
                    session=EngagedNativeSession(self.store,token)
                else:session=NativeSession(self.store,token)
                self.sessions[token]=session
                try:return await session.prepare(body)
                except BaseException:
                    session.error='Preparation did not complete'
                    await session.stop();raise
        session=self.sessions.get(token)
        if session is None:raise ValueError('Test no longer available; keep this page open and save browser notes')
        if path=='/stop':return await session.stop()
        if path=='/save':return await session.save(body)
        if session.stopped:raise ValueError('Test stopped; save your results')
        if path=='/frame':
            try:return await session.frame(body)
            except BaseException:
                session.error='Microphone frame processing failed; see browser recovery trace'
                await session.stop();raise
        if path=='/interrupt':return await session.interrupt(body)
        if path=='/played':return await session.played(body)
        raise ValueError('Unknown test action')

    async def watchdog(self):
        while True:
            await asyncio.sleep(.2)
            for s in list(self.sessions.values()):
                if s.stopped:continue
                now=time.monotonic()
                if s.error or now-s.started>180 or now-s.last_frame>(2 if s.armed else 60):
                    s.error=s.error or 'Microphone stopped sending; attempt ended safely'
                    await s.stop()
                elif (s.pending and now-s.pending['commit_monotonic']>25) or (s.current and not s.current['done'] and now-s.current['commit_monotonic']>25):
                    s.error='Reply timed out; attempt ended safely';await s.stop()
