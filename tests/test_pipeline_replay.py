"""Headless orchestration replay; all words/identities/models are controlled.

Positive identity comes from explicit fictional setup, never a voice score.
No microphone, encoder, ASR, native engine, paid provider or acoustic playback.
"""
import asyncio
from copy import deepcopy
import sqlite3
import tempfile
import threading
from pathlib import Path
import unittest

from experiments.memory.conversation_adapter import MemoryTextProvider
from experiments.memory.learning_queue import LearningQueue, LearningConversation
from experiments.memory.learning_supervisor import LearningSupervisor
from tavi.conversation_providers import Speech
from tavi.speaker_evidence import Candidate, TurnKey, compare_shadow
from tavi.storage import Store

REPLY='That sounds fun. We could make something together.'
MODEL='a'*64


class PipelineReplayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'learning.sqlite3'
        self.q=LearningQueue(self.path);self.addCleanup(self.q.close)
        self.store=Store();self.addCleanup(self.store.close)
        self.scope={'session_id':'fictional-replay','revision':1,'identity_origin':'explicit_fictional_setup',
                    'task':{'people':{'adultone':'Fictional Mira','adulttwo':'Fictional Leon'},
                            'actual_speaker_id':'adultone','audience_ids':['adultone'],'conversation_at':'2026-10-01T12:00:00Z'}}
        self.lookup_gate=None;self.voice_gate=None;self.reply_error=False;self.voice_error=False
        self.lookups=[];self.replies=[];self.voiced=[];self.refs=[];self.native_calls=[]
        self.native_gate=threading.Event();self.native_gate.set();self.native_entered=threading.Event();self.native_error=False
        owner=self
        class Client:
            def initialize(self):pass
            def ingest(self,source):
                owner.native_calls.append(deepcopy(source));owner.native_entered.set()
                if not owner.native_gate.wait(3):raise TimeoutError('Controlled native gate')
                if owner.native_error:raise OSError('Controlled ambiguous completion')
                return {'controlled':True}
            def abort(self):owner.native_error=True;owner.native_gate.set()
            def close(self):pass
        self.s=LearningSupervisor(self.path,Client);self.s.start();self.addCleanup(self.s.stop)
        class Reference:
            def __init__(self,store):self.closed=False;owner.refs.append(self)
            async def connect(self):pass
            async def reply(self,task,evidence,case_id):
                owner.replies.append(deepcopy((task,evidence)))
                if owner.reply_error:raise RuntimeError('Controlled reply failure')
                return {'text':REPLY,'status':'completed'}
            async def close(self):self.closed=True
        class Voice:
            async def synthesize(self,text):
                owner.voiced.append(text)
                if owner.voice_gate:await owner.voice_gate.wait()
                if owner.voice_error:raise OSError('Controlled voice failure')
                return Speech(text.encode(),100)
        async def recall(task):
            self.lookups.append(deepcopy(task))
            if self.lookup_gate:await self.lookup_gate.wait()
            sources=self.q.sources()
            return {'evidence':{'facts':[{'text':s['text'],'sources':[s['id']]} for s in sources]},'sources':sources}
        scope=lambda:{**deepcopy(self.scope),'memory_epoch':self.q.generation()}
        self.provider=MemoryTextProvider(self.store,scope=scope,recall=recall,reference_factory=Reference)
        self.c=LearningConversation(self.store,provider=self.provider,speech=Voice(),context_revision=scope,
                                   learning_queue=self.q,learning_notify=self.s.notify)
        self.lease='replay';self.c.start(self.lease);self.addAsyncCleanup(self.c.close)

    def feed(self,text='Paprika, I like making fictional paper boats.',number=1,recognition=None):
        self.c.feed(self.lease,{'events':[{'type':'speech_started','utterance':number},
            {'type':'recognition','utterance':number,'text':text,'final':True,'recognition_id':recognition or str(number)}]})

    async def wait(self,fn):
        async with asyncio.timeout(2):
            while not fn():await asyncio.sleep(.002)

    async def settle(self):
        for _ in range(50):await asyncio.sleep(0)

    async def ready(self):
        await self.wait(lambda:self.c.audio is not None or self.c.failure is not None)
        self.assertIsNone(self.c.failure)

    async def play(self):
        await self.ready();response=self.c.controller.token.response_id
        async with asyncio.timeout(2):
            while self.c.completed_response_id!=response:
                if self.c.audio:
                    a=self.c.audio;body={'response_id':a['id'],'sequence':a['sequence']}
                    self.assertTrue(self.c.command(self.lease,'started',body));self.assertTrue(self.c.command(self.lease,'played',body))
                await asyncio.sleep(.002)

    def shadow(self,*,quality=True,turn=None):
        v=[1.0]+[0.0]*511
        p=Candidate('adultone','1'*32,MODEL,'c'*64,tuple(v))
        turn=turn or TurnKey('fictional-replay','capture1','b'*64,0)
        return compare_shadow(turn,v,MODEL,(p,),quality_eligible=quality),p

    async def test_idle_speech_does_not_query_learn_or_prepare_reply(self):
        self.feed('I like paper boats.');await self.settle()
        self.assertEqual(self.lookups,[]);self.assertEqual(self.replies,[]);self.assertEqual(self.q.pending(),0)

    async def test_accepted_source_background_save_and_actual_played_history(self):
        self.feed();await self.play();await self.wait(lambda:self.q.pending()==0)
        self.assertEqual(len(self.q.sources()),1);self.assertEqual(len(self.native_calls),1)
        self.assertEqual(self.c.history[-1],{'role':'assistant','content':REPLY})
        self.assertEqual(len(self.q.diagnostics()['sources'][0]['events']),4)

    async def test_same_person_followup_without_name_retains_only_played_context(self):
        self.feed();await self.play();self.scope['task']['conversation_at']='2026-10-01T12:01:00Z'
        self.feed('Could we make it blue?',2);await self.play()
        self.assertEqual(len(self.replies),2);self.assertEqual(self.replies[-1][0]['recent_conversation'][-1]['content'],REPLY)

    async def test_speaker_switch_without_poll_retires_private_history_and_attributes_new_source(self):
        self.feed('Paprika, my private project is a paper castle.');await self.play();await self.wait(lambda:self.q.pending()==0)
        self.scope['task']['actual_speaker_id']='adulttwo';self.scope['task']['audience_ids']=['adulttwo']
        self.feed('What could we make?',2);await self.play();await self.wait(lambda:self.q.pending()==0)
        self.assertEqual(self.replies[-1][0]['recent_conversation'],[])
        self.assertEqual(self.q.sources()[-1]['speaker_id'],'adulttwo');self.assertEqual(self.q.sources()[0]['speaker_id'],'adultone')

    async def test_audience_switch_without_poll_drops_history_and_private_native_facts(self):
        self.feed('Paprika, a private paper-castle idea for me alone.');await self.play();await self.wait(lambda:self.q.pending()==0)
        private_source=self.q.sources()[0]['id']
        self.scope['task']['audience_ids'].append('adulttwo');self.feed('What could we make?',2);await self.play()
        self.assertEqual(self.replies[-1][0]['recent_conversation'],[])
        # The newly accepted shared question may already be saved. Its allowed
        # source can remain; it must not smuggle the earlier private source.
        self.assertNotIn(private_source,str(self.replies[-1][1]))
        self.assertNotIn('paper-castle',str(self.replies[-1][1]))

    async def test_profile_revision_between_turns_retires_prior_context(self):
        self.scope['profile_revision']='old';self.feed();await self.play()
        self.scope['profile_revision']='new';self.feed('What next?',2);await self.play()
        self.assertEqual(self.replies[-1][0]['recent_conversation'],[])

    async def test_exact_shadow_similarity_never_authorizes_lookup_or_learning(self):
        evidence,_=self.shadow();self.assertEqual(evidence.scores[0].cosine,1)
        self.scope['task']['actual_speaker_id']=evidence.speaker_id;self.feed();await self.settle()
        self.assertEqual(self.lookups,[]);self.assertEqual(self.replies,[]);self.assertEqual(self.native_calls,[])
        self.assertEqual(self.q.pending(),0);self.assertEqual(self.c.learning_events[-1]['reason'],'unknown_speaker')

    async def test_explicitly_labelled_short_or_overlap_fixture_remains_unqualified(self):
        for n,label in enumerate(('short','overlap'),1):
            evidence,_=self.shadow(quality=False);self.scope['task']['actual_speaker_id']=evidence.speaker_id
            self.feed('Paprika, a controlled '+label+' example.',n);await self.settle()
        self.assertEqual(self.lookups,[]);self.assertEqual(self.native_calls,[]);self.assertEqual(self.q.pending(),0)

    async def test_stale_capture_shadow_result_rejected_before_turn_scope_assignment(self):
        evidence,p=self.shadow();turn=TurnKey('fictional-replay','later-capture','b'*64,0)
        with self.assertRaises(ValueError):evidence.require_current(turn,MODEL,(p,))
        self.assertEqual(self.lookups,[]);self.assertEqual(self.native_calls,[])

    async def test_cancel_during_lookup_closes_connection_and_publishes_no_audio(self):
        self.lookup_gate=asyncio.Event();self.feed();await self.wait(lambda:len(self.lookups)==1)
        rid=self.c.controller.token.response_id;self.c.command(self.lease,'interrupt',{'response_id':rid})
        self.lookup_gate.set();await self.settle()
        self.assertEqual(self.replies,[]);self.assertIsNone(self.c.audio);self.assertTrue(self.refs[0].closed)

    async def test_scope_change_during_lookup_without_poll_blocks_reply(self):
        self.lookup_gate=asyncio.Event();self.feed();await self.wait(lambda:len(self.lookups)==1)
        self.scope['task']['audience_ids'].append('adulttwo');self.lookup_gate.set();await self.settle()
        self.assertEqual(self.replies,[]);self.assertIsNone(self.c.audio);self.assertEqual(self.c.history,[])

    async def test_scope_change_during_private_synthesis_blocks_audio(self):
        self.voice_gate=asyncio.Event();self.feed();await self.wait(lambda:len(self.voiced)>0)
        self.scope['revision']=2;self.voice_gate.set();await self.settle()
        self.assertIsNone(self.c.audio);self.assertEqual(self.c.history,[])

    async def test_reply_available_while_background_save_blocked(self):
        self.native_gate.clear();self.feed();await self.ready();await self.wait(self.native_entered.is_set)
        self.assertEqual(self.q.sources(),[]);self.assertEqual(self.q.working(),1)
        self.native_gate.set();await self.wait(lambda:self.q.pending()==0);self.assertIsNotNone(self.c.audio)

    async def test_revocation_during_native_work_blocks_late_completion_and_audio(self):
        self.native_gate.clear();self.feed();await self.ready();await self.wait(self.native_entered.is_set)
        self.q.revoke(self.native_calls[0]['id']);self.assertIsNone(self.c.snapshot()['audio'])
        self.native_gate.set();await self.wait(lambda:self.s.snapshot()['late_blocked']==1)
        self.assertEqual(self.q.sources(),[]);self.assertEqual(self.c.history,[])

    async def test_backlog_preserves_reply_but_records_unsaved_memory(self):
        self.q.maximum_pending=1;self.native_gate.clear();self.feed();await self.ready();await self.wait(self.native_entered.is_set)
        self.feed('A different fictional project.',2);await self.ready()
        self.assertEqual(self.c.learning_events[-1]['reason'],'learning_backlog');self.assertEqual(len(self.native_calls),1)
        self.native_gate.set();await self.wait(lambda:self.q.pending()==0)

    async def test_sqlite_write_lock_exposes_learning_failure_without_reply_failure(self):
        blocker=LearningQueue(self.path);self.addCleanup(blocker.close)
        with blocker.db:
            blocker.db.execute('BEGIN IMMEDIATE');self.feed()
        await self.ready();self.assertEqual(self.c.learning_events[-1]['reason'],'local_learning_storage_error')
        self.assertEqual(self.q.pending(),0)

    async def test_ambiguous_native_completion_is_not_retried_on_supervisor_restart(self):
        self.native_error=True;self.feed();await self.ready();await self.wait(lambda:self.s.snapshot()['status']=='needs_reconciliation')
        self.s.stop();called=[];second=LearningSupervisor(self.path,lambda:called.append(True));self.addCleanup(second.stop);second.start()
        await self.wait(lambda:second.snapshot()['status']=='needs_reconciliation')
        self.assertEqual(called,[]);self.assertEqual(len(self.native_calls),1);self.assertEqual(self.q.working(),1)

    async def test_reply_failure_cannot_publish_or_learn_assistant_text(self):
        self.reply_error=True;self.feed();await self.wait(lambda:self.c.failure is not None);await self.wait(lambda:self.q.pending()==0)
        self.assertIsNone(self.c.audio);self.assertEqual(self.voiced,[]);self.assertEqual(len(self.replies),1)
        self.assertFalse(any(m['role']=='assistant' for m in self.c.history));self.assertNotIn(REPLY,str(self.q.sources()))

    async def test_voice_failure_cannot_publish_or_remember_unheard_reply(self):
        self.voice_error=True;self.feed();await self.wait(lambda:self.c.failure is not None)
        self.assertIsNone(self.c.audio);self.assertEqual(self.c.failure['component'],'speech')
        self.assertFalse(any(m['role']=='assistant' for m in self.c.history))

    async def test_mute_reconnect_discards_late_audio_ack_and_asr_events(self):
        self.feed();await self.ready();a=dict(self.c.audio);self.c.stop(self.lease)
        with self.assertRaises(ValueError):self.c.audio_bytes(self.lease,a['id'],a['sequence'])
        self.assertFalse(any(m['role']=='assistant' for m in self.c.history))
        self.lease='new-lease';self.c.start(self.lease)
        self.c.feed(self.lease,{'events':[{'type':'recognition','utterance':1,'text':'A late old transcript.','final':True}]})
        self.assertEqual(self.c.history,[]);self.assertIsNone(self.c.audio)
        self.feed('Paprika, hello again.',2);await self.play();self.assertNotIn('late old',str(self.c.history))

    async def test_recognition_redelivery_after_restart_does_not_duplicate_source(self):
        text='Paprika, I like folding fictional paper boats.'
        self.feed(text,recognition='stable');await self.play();await self.wait(lambda:self.q.pending()==0)
        self.c.stop(self.lease);self.c.start(self.lease)
        self.feed(text,2,recognition='stable');await self.play();await self.wait(lambda:self.q.pending()==0)
        self.assertEqual(len(self.native_calls),1);self.assertEqual(len(self.q.sources()),1)
        self.assertTrue(self.c.learning_events[-1]['duplicate'])
