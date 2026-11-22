"""Trusted voice/audience routing for the Mac host. Unknown never gets a bank.

Real profiles/policies come only from local collection and independent gates.
Text claiming a name, roleplay and model output cannot change this authority.
"""
import asyncio
from contextlib import aclosing
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path
from uuid import uuid4
from tavi.identity_catalog import ProfileCatalog,PEOPLE
from tavi.identity_policy import QualifiedPolicy
from tavi.speaker_profile import ROOT,VOICE
from tavi.speaker_process import SpeakerProcess
from tavi.live_identity import LiveIdentity,VoiceDecision
from tavi.companion_text import CompanionText
from tavi.household_memory import HouseholdMemory


class HouseholdProvider:
    from tavi.realtime_reference import MODEL as model
    def __init__(self,host,store):
        from experiments.memory.conversation_adapter import MemoryTextProvider
        from experiments.memory.access_evidence import with_access_decision
        self.host=host;self.anonymous=CompanionText(store)
        self.personal=MemoryTextProvider(store,scope=host.scope,recall=host.bank.recall,evidence_qualifier=with_access_decision)
    @property
    def memory_enabled(self):return self.host.allowed()
    async def stream_reply(self,history):
        provider=self.personal if self.host.allowed() else self.anonymous
        async with aclosing(provider.stream_reply(history)) as stream:
            async for delta in stream:yield delta
    async def close(self):await self.personal.close();await self.anonymous.close()


class HouseholdRuntime:
    def __init__(self,*,catalog=None,encoder=None,bank=None,policy_loader=QualifiedPolicy.load):
        self.people={p:v['name'] for p,v in PEOPLE.items()};self.catalog=catalog or ProfileCatalog()
        self.model=json.loads((ROOT/'experiments/speaker-id/model-manifest.json').read_text())['sha256']
        self.voice=LiveIdentity(self.catalog,encoder or SpeakerProcess(),self.model)
        self.bank=bank or HouseholdMemory(self.people);self.policy_loader=policy_loader
        self.voice_enabled=False;self.memory_consent=False;self.family_audience=False;self.speaker='unknown'
        self.identity_reason='not_started';self.policy=None;self.session_id=uuid4().hex
        self.at=datetime.now(timezone.utc).isoformat();self.conversation_instance=None;self.policy_stat=None

    async def prepare(self,body):
        # Reset previous speaker before any possible exception in setup.
        self.speaker='unknown';self.memory_consent=False;self.family_audience=False;self.voice.reset(None);self.session_id=uuid4().hex
        voice=body.get('family_voice',False);memory=body.get('family_memory',False);audience=body.get('family_only_audience',False)
        if any(type(x) is not bool for x in (voice,memory,audience)):raise ValueError('Choose family voice/memory settings explicitly')
        if memory and (not voice or not audience or not body.get('online')):
            await self.bank.close()
            raise ValueError('Family memory needs local voice recognition, online replies and a family-only room')
        if not memory:await self.bank.close()
        self.voice_enabled=voice;self.policy=None;self.policy_stat=None
        if voice:
            await asyncio.to_thread(self.catalog.refresh)
            try:self.policy=self.policy_loader(VOICE/'identity-policy.json',self.catalog,self.model)
            except (OSError,ValueError,KeyError):self.policy=None
            self.voice.policy=self.policy
            if self.policy:self.policy_stat=self.catalog._stat(VOICE/'identity-policy.json')
            await asyncio.to_thread(self.voice.prepare)
        if memory:
            if not self.policy:
                await self.bank.close()
                raise ValueError('Finish independent family voice checks before enabling memories')
            if not self.bank.qualified:
                await self.bank.close()
                raise ValueError('Household memory integration checks are still pending; ordinary conversation is available')
            await self.bank.prepare()
        self.memory_consent=memory;self.family_audience=audience

    def reset(self,lease):self.voice.reset(lease)
    def submit(self,lease,utterance,pcm):
        if self.voice_enabled:self.voice.submit(lease,utterance,pcm)

    def resolve(self,lease,utterance,token):
        self.speaker='unknown';self.at=datetime.now(timezone.utc).isoformat()
        try:
            result=self.voice.latch(lease,utterance) if self.voice_enabled else VoiceDecision('unknown','not_enabled')
            if self.valid_policy() and result.policy_revision==self.policy.certificate_sha256:self.speaker=result.speaker_id
            self.identity_reason=result.reason
        except Exception:self.identity_reason='voice_unavailable'
        return self.speaker

    def valid_policy(self):
        if not self.policy or not self.catalog.current():return False
        try:return self.catalog._stat(VOICE/'identity-policy.json')==self.policy_stat
        except OSError:return False

    def allowed(self):
        c=self.conversation_instance
        return bool(self.memory_consent and self.family_audience and self.bank.ready and self.bank.qualified and self.valid_policy()
                    and self.speaker in self.people and c and c.controller._speaker==self.speaker)

    def scope(self):
        valid=not self.voice_enabled or self.catalog.current()
        speaker=self.speaker if valid and self.valid_policy() else 'unknown'
        conversation_id=self.conversation_instance.controller.session_id if self.conversation_instance else 'starting'
        return {'session_id':self.session_id+':'+conversation_id,'task':{'people':self.people,'actual_speaker_id':speaker,
            'audience_ids':sorted(self.people) if self.family_audience else [],'conversation_at':self.at,'catalogue':[]},
            'profiles_revision':self.catalog.revision if self.voice_enabled else 'off','policy_revision':self.policy.certificate_sha256 if self.valid_policy() else None,
            'memory_consent':self.memory_consent,'memory_epoch':self.bank.generation(),'storage_current':valid}

    def capture(self,scope,token,text,recognition_id):
        if not self.allowed() or scope!=self.scope():return {'queued':False,'reason':'unknown_or_unqualified_identity_or_audience'}
        return self.bank.capture(scope,token,text,recognition_id)

    def conversation(self,store,*,speech):
        from experiments.memory.learning_queue import LearningConversation
        result=LearningConversation(store,provider=HouseholdProvider(self,store),speech=speech,context_revision=self.scope,
            sentence_minimum=1,learning_queue=self,learning_notify=self.bank.notify,identity_resolver=self.resolve)
        self.conversation_instance=result;return result

    def status(self):
        memory=self.bank.status()
        return {'family_voice_enabled':self.voice_enabled,'voice_status':'qualified_component' if self.valid_policy() else 'calibration_required',
            'speaker_id':self.speaker if self.valid_policy() else 'unknown','identity_reason':self.identity_reason,
            'family_memory_requested':self.memory_consent,'memory_active_for_turn':self.allowed(),
            'family_only_audience':self.family_audience,'personal_only_memories_enabled':False,'memory':memory}

    async def close(self):await self.bank.close();await asyncio.to_thread(self.voice.close)
