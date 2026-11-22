"""Current Mac controller replay with synthetic text events and valid tone WAVs.

Anonymous/unqualified production path, fake native transport and speech only.
Not ASR, K, acoustic playback, calibrated identity or a wall-time soak.
"""
import asyncio
from io import BytesIO
import hashlib
import json
import threading
import wave
from types import SimpleNamespace

from experiments.memory.native_text import NativeTextReference
from tavi.conversation_providers import Speech
from tavi.household_memory import HouseholdMemory
from tavi.household_runtime import HouseholdRuntime
from tavi.local_speech import validate_wave
from tavi.storage import Store

TEXT='A small cardboard boat could work. We can make a bright flag for it.'
PROMPT='839fdeba91f1c19d006cf7ff35d4894ad023188a6ff35f35a23c001b2fceea5f'


def tone_wave():
    import math,struct
    out=BytesIO()
    with wave.open(out,'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000)
        wav.writeframes(b''.join(struct.pack('<h',int(800*math.sin(2*math.pi*440*n/24000))) for n in range(2400)))
    data=out.getvalue();validate_wave(data,24000);return data


class NoMemoryBank:
    qualified=False;ready=False
    def __init__(self):self.calls=0
    def generation(self):return ('off',0)
    async def recall(self,task):self.calls+=1;raise AssertionError('Unqualified anonymous replay touched memory')
    def capture(self,*args):self.calls+=1;raise AssertionError('Unqualified replay learned persistent memory')
    def notify(self):pass
    async def close(self):pass


class NoEncoder:
    def prepare(self):raise AssertionError('No voice calibration or encoding allowed')
    def encode(self,*args):raise AssertionError('No real voice data allowed')
    def close(self):pass


class ActiveReplay:
    def __init__(self):
        self.store=Store();self.bank=NoMemoryBank();self.now=1000.;self.n=0;self.mode='normal';self.voice_failure=False
        self.refs=[];self.sent=0;self.wav=tone_wave();self.max_history=0;self.max_chunks=0;self.max_tasks=0;self.acks=0
        self.trace=[];self.closed=False
        catalog=SimpleNamespace(revision='fictional',candidates=(),current=lambda:True,refresh=lambda:None)
        self.host=HouseholdRuntime(catalog=catalog,encoder=NoEncoder(),bank=self.bank)
        owner=self
        class Voice:
            async def synthesize(self,text):
                await asyncio.sleep(0)
                if owner.voice_failure:raise OSError('Controlled local speech failure')
                return Speech(owner.wav,100)
            async def close(self):pass
        self.c=self.host.conversation(self.store,speech=Voice());self.c.clock=lambda:self.now
        class Reference(NativeTextReference):
            async def connect(self):self.closed=False;self.step=0;self.pending=asyncio.Event();self.release=asyncio.Event();self.mode=owner.mode
            async def send(self,kind,**fields):
                assert kind=='response.create';wire=fields['response'];payload=json.loads(wire['input'][0]['content'][0]['text'])
                assert hashlib.sha256(wire['instructions'].encode()).hexdigest()==PROMPT
                assert payload['task']['actual_speaker_id']=='anonymous' and not payload['memory_evidence']['facts']
                self.case=wire['metadata']['case_id'];self.response='fake-'+self.case;owner.sent+=1;owner.refs.append(self)
            async def receive(self):
                await asyncio.sleep(0);self.step+=1
                if self.step==1:return {'type':'response.created','response':{'id':self.response,'metadata':{'case_id':self.case}}}
                if self.step==2:return {'type':'response.output_text.delta','response_id':self.response,'delta':TEXT}
                if self.mode=='pending':self.pending.set();await self.release.wait()
                if self.mode=='provider-error':raise OSError('Controlled provider disconnection')
                return {'type':'response.done','response':{'id':self.response,'status':'incomplete' if self.mode=='incomplete' else 'completed',
                    'usage':{'input_tokens':1,'output_tokens':1},'output':[{'content':[{'type':'output_text','text':TEXT}]}]}}
            async def close(self):self.closed=True
        self.c.provider.anonymous.reference_factory=lambda s:Reference(s)
        self.c.provider.personal.reference_factory=lambda s:(_ for _ in ()).throw(AssertionError('Personal model route used without qualification'))
        self.restart()
    def restart(self,online=True):
        self.mode='normal';self.voice_failure=False;self.c.start('replay-'+str(self.n),online=online);self.lease=self.c.lease
    def feed(self,text):
        self.n+=1;self.now+=.032
        self.c.feed(self.lease,{'events':[{'type':'speech_started','utterance':self.n},
            {'type':'recognition','utterance':self.n,'final':True,'text':text,'recognition_id':'synthetic-'+str(self.n)}]})
    def sample(self):
        self.max_history=max(self.max_history,len(self.c.history));self.max_chunks=max(self.max_chunks,len(self.c.chunks));self.max_tasks=max(self.max_tasks,len(self.c.tasks))
        assert self.max_history<=12 and self.max_chunks<=2 and self.max_tasks<=3
        assert self.bank.calls==0 and not HouseholdMemory.qualified
    async def wait(self,fn):
        async with asyncio.timeout(3):
            while not fn():self.sample();await asyncio.sleep(.001)
        self.sample()
    async def drained(self):
        await self.wait(lambda:not self.c.tasks and not self.c.provider.anonymous.active and not self.c.provider.anonymous.cleanup)
    async def play(self):
        await self.wait(lambda:self.c.audio is not None or self.c.failure is not None);assert not self.c.failure
        rid=self.c.controller.token.response_id
        async with asyncio.timeout(3):
            while self.c.completed_response_id!=rid:
                self.sample()
                if self.c.audio:
                    a=self.c.audio;b={'response_id':a['id'],'sequence':a['sequence']};validate_wave(self.c.audio_bytes(self.lease,a['id'],a['sequence']),24000)
                    assert self.c.command(self.lease,'started',b);assert self.c.command(self.lease,'played',b);self.acks+=1
                    assert not self.c.command(self.lease,'played',b)
                await asyncio.sleep(.001)
        await self.drained()
    async def normal(self,text):
        self.feed(text);await self.play();assert self.c.history[-1]['content']==TEXT
    async def probe(self,name):
        self.restart();before=self.sent
        if name=='standby':
            self.feed('The cardboard is blue.');await asyncio.sleep(.01);assert self.sent==before and not self.c.engaged
        elif name=='greeting':
            self.feed('Paprika');await self.play();assert self.sent==before
        elif name=='offline':
            self.restart(online=False);self.feed('Paprika, tell me a story.');await self.play();assert self.sent==before
        elif name in ('incomplete','provider-error','voice-error'):
            self.mode=name;self.voice_failure=name=='voice-error';self.feed('Paprika, tell me a boat story.')
            await self.wait(lambda:self.c.failure is not None);assert self.c.audio is None and not self.c.chunks and not any(m['role']=='assistant' for m in self.c.history)
            await self.drained();assert self.sent==before+1
        elif name in ('cancel-generation','mute-pending','scope-change'):
            # A prior cancelled reference remains in the audit list. Wait for a
            # newly dispatched request, never that older reference's event.
            previous=len(self.refs);self.mode='pending';self.feed('Paprika, tell me a boat story.')
            await self.wait(lambda:len(self.refs)==previous+1 and self.refs[previous].pending.is_set())
            ref=self.refs[previous];assert self.sent==before+1 and ref.mode=='pending' and self.c.audio is None
            if name=='cancel-generation':assert self.c.command(self.lease,'interrupt',{'response_id':self.c.controller.token.response_id})
            elif name=='mute-pending':self.c.stop(self.lease)
            else:self.host.session_id='new-fictional-scope';self.c.snapshot()
            await self.drained();assert ref.closed;ref.release.set();assert self.c.audio is None and not self.c.chunks and not any(m['role']=='assistant' for m in self.c.history)
        elif name=='interrupt-playback':
            self.feed('Paprika, tell me a boat story.');await self.wait(lambda:self.c.audio is not None);a=dict(self.c.audio)
            assert self.c.command(self.lease,'started',{'response_id':a['id'],'sequence':a['sequence']})
            assert self.c.command(self.lease,'interrupt',{'response_id':a['id']});await self.drained()
            assert self.c.audio is None and not any(m['role']=='assistant' for m in self.c.history)
            assert not self.c.command(self.lease,'played',{'response_id':a['id'],'sequence':a['sequence']})
        elif name=='stale-after-reconnect':
            self.feed('Paprika, tell me a boat story.');await self.wait(lambda:self.c.audio is not None);old=self.lease;a=dict(self.c.audio)
            self.c.stop(old);await self.drained();self.restart()
            try:self.c.audio_bytes(old,a['id'],a['sequence']);raise AssertionError('Old audio admitted')
            except ValueError:pass
            self.c.feed(self.lease,{'events':[{'type':'recognition','utterance':999,'final':True,'text':'Late stale text.'}]})
            assert not self.c.history and self.c.audio is None
        elif name=='frame-expiry':
            self.feed('Paprika, tell me a boat story.');await self.wait(lambda:self.c.audio is not None);self.now+=3;self.c.expire();await self.drained();assert self.c.lease is None and self.c.audio is None
        elif name=='goodbye':
            await self.normal('Paprika, tell me a boat story.');self.feed('Okay thanks, bye for now.');await self.play();assert not self.c.engaged and self.c.lease==self.lease
        elif name=='paid-turn-bound':
            for n in range(13):
                self.feed('Paprika, tell me a boat story.' if n==0 else 'Tell me another one.');await self.play()
            assert self.sent-before==12 and self.c.close_after_playback is False
        else:raise ValueError(name)
        self.c.stop();await self.drained();self.sample();self.trace.append({'probe':name,'passed':True,'requests':self.sent-before})
    async def run(self,batches=30):
        completed=0
        for batch in range(batches):
            self.restart()
            for n in range(10):await self.normal('Paprika, could we build a cardboard boat?' if n==0 else 'Could we make another one?');completed+=1
            self.c.stop();await self.drained()
        probes=['standby','greeting','offline','incomplete','provider-error','voice-error','cancel-generation','mute-pending','scope-change','interrupt-playback','stale-after-reconnect','frame-expiry','goodbye','paid-turn-bound']
        for name in probes:await self.probe(name)
        return {'completed_turns':completed,'probes_passed':len(self.trace),'probe_count':len(probes),'trace':self.trace,
                'maximum_history':self.max_history,'maximum_chunks':self.max_chunks,'maximum_tasks':self.max_tasks,'playback_acks':self.acks,
                'all_references_closed':all(r.closed for r in self.refs),'no_memory_access':self.bank.calls==0,'no_encoder_calls':True,
                'fixture_uncertain_reservations_preserved':self.store.db.execute('select count(*) from spending where actual is null').fetchone()[0]>=2,
                'fixture_ledger_only':True,'real_model_requests':0,'physical_audio':False,'actual_asr':False,'actual_K':False}
    async def close(self):
        if self.closed:return
        await self.c.close();await self.host.close();self.store.close();self.closed=True
