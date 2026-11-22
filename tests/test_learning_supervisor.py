import asyncio,json,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from experiments.memory.learning_queue import LearningQueue,LearningConversation
from experiments.memory.learning_supervisor import LearningSupervisor
from tavi.storage import Store
from tavi.conversation_providers import Speech

class ControlledClient:
    def __init__(self,*,fail=False):
        self.entered=threading.Event();self.release=threading.Event();self.fail=fail;self.calls=[];self.closed=False
    def initialize(self):pass
    def ingest(self,source):
        self.calls.append(source);self.entered.set()
        if not self.release.wait(3):raise TimeoutError('Test gate')
        if self.fail:raise OSError('Ambiguous native completion')
        return {'stored':True}
    def abort(self):self.fail=True;self.release.set()
    def close(self):self.closed=True

class BackgroundLearningTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'queue.sqlite3';self.q=LearningQueue(self.path);self.addCleanup(self.q.close)
        self.store=Store();self.addCleanup(self.store.close)
        self.scope={'session_id':'visit','revision':1,'task':{'actual_speaker_id':'a','people':{'a':'Mira'},'audience_ids':['a'],'conversation_at':'2026-10-01T12:00:00Z'}}
        self.client=ControlledClient();self.s=LearningSupervisor(self.path,lambda:self.client);self.s.start();self.addCleanup(self.s.stop)
        owner=self
        class Provider:
            async def stream_reply(self,history):yield 'That sounds fun.'
            async def close(self):pass
        class Voice:
            async def synthesize(self,text):return Speech(b'wave',100)
        def scope():return {**owner.scope,'memory_epoch':owner.q.generation()}
        self.c=LearningConversation(self.store,provider=Provider(),speech=Voice(),context_revision=scope,learning_queue=self.q,learning_notify=self.s.notify)
        self.c.start('test');self.addAsyncCleanup(self.c.close)
    async def wait(self,fn):
        async with asyncio.timeout(2):
            while not fn():await asyncio.sleep(.005)
    def feed(self,n=1,text='Paprika, I like wooden gliders.'):
        self.c.feed('test',{'events':[{'type':'speech_started','utterance':n},{'type':'recognition','utterance':n,'text':text,'final':True,'recognition_id':'r'+str(n)}]})
    async def test_reply_is_ready_while_native_ingestion_still_blocked(self):
        self.feed();await self.wait(self.client.entered.is_set);await self.wait(lambda:self.c.audio is not None)
        self.assertFalse(self.client.release.is_set());self.assertEqual(self.q.sources(),[])
        self.client.release.set();await self.wait(lambda:len(self.q.sources())==1)
        self.assertEqual(self.q.generation(),0) # additions do not cancel replies
        self.assertIsNotNone(self.c.audio)
    async def test_revocation_during_native_work_blocks_completion_and_queued_audio(self):
        self.feed();await self.wait(self.client.entered.is_set);await self.wait(lambda:self.c.audio is not None)
        sid=self.client.calls[0]['id'];self.assertTrue(self.q.revoke(sid));self.assertEqual(self.q.generation(),1)
        self.assertIsNone(self.c.snapshot()['audio']);self.client.release.set()
        await self.wait(lambda:self.s.snapshot()['late_blocked']==1);self.assertEqual(self.q.sources(),[])
        self.assertEqual(self.c.history,[])
    async def test_ambiguous_error_stops_without_retry_and_restart_requires_reconciliation(self):
        self.client.fail=True;self.feed();await self.wait(self.client.entered.is_set);self.feed(2);self.client.release.set()
        await self.wait(lambda:self.s.snapshot()['failed']==1);self.s.stop()
        self.assertEqual(len(self.client.calls),1);self.assertEqual(self.q.working(),1)
        self.assertEqual(self.q.diagnostics()['sources'][0]['attempts'][0]['outcome'],'ambiguous')
        second=ControlledClient();s=LearningSupervisor(self.path,lambda:second);s.start();self.addCleanup(s.stop)
        await self.wait(lambda:s.snapshot()['status']=='needs_reconciliation');self.assertEqual(second.calls,[])
    async def test_second_owner_cannot_dispatch_or_recover_running_job(self):
        self.feed();await self.wait(self.client.entered.is_set)
        second=ControlledClient();s=LearningSupervisor(self.path,lambda:second);s.start();self.addCleanup(s.stop)
        await self.wait(lambda:s.snapshot()['status']=='owner_busy');self.assertEqual(second.calls,[]);self.assertEqual(self.q.working(),1)
    async def test_abort_does_not_publish_native_result(self):
        self.feed();await self.wait(self.client.entered.is_set);await asyncio.to_thread(self.s.stop)
        self.assertEqual(self.q.sources(),[]);self.assertEqual(self.q.working(),1);self.assertTrue(self.client.closed)
        self.assertEqual(self.q.diagnostics()['sources'][0]['attempts'][0]['outcome'],'aborted')
    async def test_backlog_rejection_does_not_break_reply(self):
        self.q.maximum_pending=1;self.feed();await self.wait(self.client.entered.is_set);self.feed(2)
        await self.wait(lambda:self.c.audio is not None)
        self.assertEqual(self.c.learning_events[-1]['reason'],'learning_backlog');self.assertIsNone(self.c.failure)
    async def test_storage_lock_is_visible_failure_but_reply_continues(self):
        blocker=LearningQueue(self.path);self.addCleanup(blocker.close)
        with blocker.db:
            blocker.db.execute('BEGIN IMMEDIATE');self.feed()
        await self.wait(lambda:self.c.audio is not None)
        self.assertEqual(self.c.learning_events[-1]['reason'],'local_learning_storage_error');self.assertIsNone(self.c.failure)

class SourceIdentityTests(unittest.TestCase):
    def test_recognition_redelivery_survives_restart_with_same_source_and_time(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'learning.sqlite3';q=LearningQueue(p)
            scope={'session_id':'visit','task':{'actual_speaker_id':'a','people':{'a':'Mira'},'audience_ids':['a'],'conversation_at':'2026-10-01T12:00:00Z'}}
            first=q.capture(scope,SimpleNamespace(response_id='first'),'I enjoy boats.','recognition');q.close();q=LearningQueue(p)
            scope['task']['conversation_at']='2026-10-02T12:00:00Z'
            second=q.capture(scope,SimpleNamespace(response_id='new-controller'),'I enjoy boats.','recognition')
            self.assertTrue(second['duplicate']);self.assertEqual(first['source_id'],second['source_id']);self.assertEqual(q.pending(),1)
            self.assertEqual(q.claim()['source']['at'],'2026-10-01T12:00:00Z')
            with self.assertRaises(ValueError):q.capture(scope,SimpleNamespace(response_id='new'),'Altered words.','recognition')
            q.close()
