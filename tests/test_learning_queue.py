import tempfile,unittest
import asyncio
from pathlib import Path
from types import SimpleNamespace
from experiments.memory.learning_queue import LearningQueue
from experiments.memory.learning_queue import LearningConversation
from tavi.storage import Store
from tavi.conversation_providers import Speech
class LearningQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'queue.sqlite3';self.q=LearningQueue(self.path);self.addCleanup(lambda:self.q.close())
        self.scope={'session_id':'visit1','task':{'actual_speaker_id':'a','audience_ids':['a'],'people':{'a':'Mira'},'conversation_at':'2026-10-01T12:00:00Z'}}
        self.token=SimpleNamespace(response_id='one')
    def test_literal_source_duplicate_and_restart(self):
        result=self.q.capture(self.scope,self.token,'I enjoy making gliders.','r')
        self.assertTrue(result['queued']);job=self.q.claim();self.assertEqual(job['source']['text'],'I enjoy making gliders.')
        self.assertTrue(self.q.complete(job));self.assertFalse(self.q.capture(self.scope,self.token,'I enjoy making gliders.','r')['queued'])
        before=self.q.sources();self.q.close();self.q=LearningQueue(self.path);self.assertEqual(self.q.sources(),before)
        with self.assertRaises(ValueError):self.q.capture(self.scope,self.token,'Different source.','r')
    def test_unknown_is_not_queued(self):
        self.scope['task']['actual_speaker_id']='unknown'
        self.assertFalse(self.q.capture(self.scope,self.token,'I enjoy gliders.','r')['queued']);self.assertEqual(self.q.pending(),0)
    def test_revocation_rejects_late_completion_and_survives_restart(self):
        sid=self.q.capture(self.scope,self.token,'Secret project.','r')['source_id'];job=self.q.claim()
        self.assertTrue(self.q.revoke(sid));self.assertFalse(self.q.complete(job));self.assertFalse(self.q.recover_stopped_job(job));self.assertEqual(self.q.sources(),[])
        self.q.close();self.q=LearningQueue(self.path);self.assertEqual(self.q.sources(),[])
    def test_stopped_job_recovery_invalidates_old_token(self):
        self.q.capture(self.scope,self.token,'A fact.','r');old=self.q.claim();self.assertTrue(self.q.recover_stopped_job(old));new=self.q.claim()
        self.assertFalse(self.q.complete(old));self.assertTrue(self.q.complete(new))

class AcceptedLearningTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.q=LearningQueue(Path(self.temp.name)/'queue.sqlite3');self.addCleanup(self.q.close)
        self.store=Store();self.addCleanup(self.store.close)
        self.scope={'session_id':'one','revision':1,'task':{'actual_speaker_id':'a','people':{'a':'Mira','b':'Leon'},'audience_ids':['a'],'conversation_at':'2026-10-01T12:00:00Z'}}
        class Provider:
            async def stream_reply(self,history):yield 'I enjoy boats too.'
            async def close(self):pass
        class Voice:
            async def synthesize(self,text):return Speech(b'wave',100)
        self.c=LearningConversation(self.store,provider=Provider(),speech=Voice(),context_revision=lambda:self.scope,learning_queue=self.q)
        self.c.start('test');self.addAsyncCleanup(self.c.close)
    def feed(self,text,n=1):
        self.c.feed('test',{'events':[{'type':'speech_started','utterance':n},{'type':'recognition','utterance':n,'text':text,'final':True,'recognition_id':str(n)}]})
    async def settle(self):
        for _ in range(20):await asyncio.sleep(0)
    async def test_unengaged_local_stop_and_assistant_output_not_learned(self):
        self.feed('I enjoy boats.');await self.settle();self.assertEqual(self.q.pending(),0)
        self.feed('Paprika, stop.',2);await self.settle();self.assertEqual(self.q.pending(),0)
        self.feed('Paprika, I enjoy gliders.',3);await self.settle()
        self.assertEqual(self.q.pending(),1);job=self.q.claim()
        self.assertIn('gliders',job['source']['text']);self.assertNotIn('boats',job['source']['text'])
    async def test_scope_is_captured_before_async_reply_or_later_audience_change(self):
        self.feed('Paprika, this is private.');self.scope['task']['audience_ids'].append('b');await self.settle()
        self.assertEqual(self.q.claim()['source']['audience_ids'],['a'])
    async def test_unknown_source_rejected_on_actual_controller_hook(self):
        self.scope['task']['actual_speaker_id']='unknown';self.feed('Paprika, I enjoy gliders.');await self.settle()
        self.assertEqual(self.q.pending(),0);self.assertEqual(self.c.learning_events[-1]['reason'],'unknown_speaker')
    async def test_listen_acknowledgement_preserves_human_source_only_when_online(self):
        self.feed('Paprika, I feel upset. Just listen.');await self.settle()
        job=self.q.claim();self.assertIn('I feel upset',job['source']['text'])
        self.assertNotIn('listening.',job['source']['text']);self.assertEqual(self.c.paid_turns,0)
        self.c.stop();self.c.start('test',online=False)
        self.feed('Paprika, just listen.',2);await self.settle()
        self.assertEqual(self.q.pending(),1) # original claimed job only
