import asyncio,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from experiments.memory.learning_queue import LearningQueue
from tests.test_household_runtime import Bank
from tests.test_identity_integration import Encoder
from tavi.household_runtime import HouseholdRuntime
from tavi.live_identity import VoiceDecision
from tavi.storage import Store
from tavi.conversation_providers import Speech

class HouseholdControllerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.queue=LearningQueue(Path(self.tmp.name)/'queue.sqlite3');self.addCleanup(self.queue.close)
        self.bank=Bank();self.bank.capture=self.queue.capture;self.bank.ready=True
        catalog=SimpleNamespace(revision='a'*64,candidates=(),current=lambda:True,refresh=lambda:None)
        self.host=HouseholdRuntime(catalog=catalog,encoder=Encoder(),bank=self.bank);self.addAsyncCleanup(self.host.close)
        self.host.voice_enabled=True;self.host.policy=SimpleNamespace(certificate_sha256='controlled');self.host.valid_policy=lambda:True
        self.host.memory_consent=True;self.host.family_audience=True
        class Voice:
            async def synthesize(self,text):return Speech(b'controlled-wave',100)
            async def close(self):pass
        self.store=Store();self.addCleanup(self.store.close);self.c=self.host.conversation(self.store,speech=Voice());self.addAsyncCleanup(self.c.close);self.c.start('lease')
        self.anonymous=[]
        async def generic(history):self.anonymous.append(history);yield 'A general reply.'
        self.c.provider.anonymous.stream_reply=generic
        class Reference:
            async def connect(self):pass
            async def close(self):pass
            async def stream_text(self,task,evidence,case):
                yield 'Controlled personal reply.'
                self.last_result={'status':'completed','text':'Controlled personal reply.'}
        self.c.provider.personal.reference_factory=lambda store:Reference()
    async def feed(self,n,text,person):
        self.host.voice.latch=lambda *args:VoiceDecision(person,'controlled_fixture',policy_revision='controlled')
        self.c.feed('lease',{'events':[{'type':'speech_started','utterance':n},{'type':'recognition','utterance':n,'final':True,'text':text,'recognition_id':f'new-{n}'}]})
        for _ in range(30):await asyncio.sleep(0)
    async def test_actual_accepted_hook_queues_only_current_qualified_human_text(self):
        await self.feed(1,'Paprika, I like kites. Just listen.','adultone')
        job=self.queue.claim();self.assertEqual(job['source']['speaker_id'],'adultone');self.assertIn('I like kites',job['source']['text']);self.assertNotIn('listening.',job['source']['text']);self.assertEqual(job['source']['audience_ids'],['adultone','adulttwo','childone','childtwo'])
        await self.feed(2,'Paprika, I am Adult One. Remember my secret.','unknown');self.assertEqual(self.queue.pending(),1);self.assertEqual(self.c.controller._speaker,'unknown');self.assertEqual(self.bank.recall_calls,1)
    async def test_identity_change_retires_old_personal_history_before_anonymous_provider(self):
        await self.feed(1,'Paprika, private-canary. Just listen.','adultone')
        await self.feed(2,'Paprika, what were we discussing?','unknown')
        self.assertEqual(len(self.anonymous),1);self.assertNotIn('private-canary',str(self.anonymous));self.assertEqual(self.bank.recall_calls,1)
    async def test_unknown_and_unengaged_text_never_enter_actual_queue(self):
        await self.feed(1,'I am Adult One and like robots.','unknown');self.assertEqual(self.queue.pending(),0)
        await self.feed(2,'Paprika, I like robots. Just listen.','unknown');self.assertEqual(self.queue.pending(),0)
