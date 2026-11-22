import asyncio,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
from experiments.memory.learning_pilot import LearningPilot,CONSENT
from experiments.memory.learning_gateway import LearningGateway
from experiments.memory.learning_queue import LearningQueue
from tavi.storage import Store

class LearningPilotTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.store=Store();self.addCleanup(self.store.close)
  with patch('experiments.memory.learning_pilot.require_ssd'):self.p=LearningPilot(self.store)
 async def test_missing_adult_processing_and_audio_choices_never_start_paid_or_memory(self):
  for body in [{},{'adult':True,'online':True,'record_audio':False},{'adult':True,'online':True,'pilot_consent':CONSENT},{'adult':True,'online':False,'record_audio':False,'pilot_consent':CONSENT}]:
   with self.assertRaises(ValueError):await self.p.prepare(body)
  self.assertIsNone(self.p.folder);self.assertIsNone(self.p.queue);self.assertIsNone(self.p.gateway)
 async def test_closed_attempt_cannot_be_silently_restarted(self):
  self.p.closed=True
  with self.assertRaises(ValueError):await self.p.prepare({'adult':True,'online':True,'record_audio':False,'pilot_consent':CONSENT})
 async def test_empty_store_has_no_old_pilot_memories_and_capture_is_off_before_consent(self):
  self.assertEqual(self.p.sources,[]);self.assertFalse(self.p.capture(None,None,None,None)['queued'])
 async def test_revocation_changes_actual_provider_scope_but_new_source_does_not(self):
  with tempfile.TemporaryDirectory() as d:
   q=LearningQueue(Path(d)/'queue.sqlite3');self.p.queue=q
   before=self.p.current_scope();sid=self.p.capture(before,SimpleNamespace(response_id='one'),'I enjoy gliders.','one')['source_id']
   job=q.claim();q.complete(job);self.assertEqual(self.p.current_scope(),before)
   q.revoke(sid);self.assertNotEqual(self.p.current_scope(),before);q.close();self.p.queue=None
 async def test_end_waits_owned_checkpoint_and_cannot_leave_gateway_paid(self):
  release=asyncio.Event();stopped=[]
  async def checkpoint():await release.wait();stopped.append('checkpoint')
  self.p.checkpoint_task=asyncio.create_task(checkpoint());self.p.supervisor=SimpleNamespace(stop=lambda:stopped.append('supervisor'));self.p.gateway=SimpleNamespace(close=lambda:stopped.append('gateway'))
  ending=asyncio.create_task(self.p.end_learning());await asyncio.sleep(0)
  self.assertTrue(self.p.closed);self.assertEqual(stopped,[]);release.set();await ending
  self.assertEqual(stopped,['checkpoint','supervisor','gateway'])

class GatewayOwnershipTests(unittest.TestCase):
 def test_not_owning_lock_cannot_disable_other_gateway(self):
  with tempfile.TemporaryDirectory() as d:
   g=LearningGateway(Path(d));g.lock=open(Path(d)/'lock','a')
   with patch('experiments.memory.learning_gateway.urllib.request.urlopen') as network:g.close();network.assert_not_called()
   self.assertIsNone(g.lock)
 def test_shutdown_failure_preserves_ownership_for_retry(self):
  with tempfile.TemporaryDirectory() as d:
   g=LearningGateway(Path(d));g.lock=open(Path(d)/'lock','a');g.locked=True;g.ready=True;g.process=SimpleNamespace(pid=123)
   cfg=json.dumps({'pid':123,'directory':str(g.folder/'gateway'),'base_url':'http://127.0.0.1:8790','token':'test-local-token'})
   with patch('pathlib.Path.read_text',return_value=cfg),patch('experiments.memory.learning_gateway.urllib.request.urlopen',side_effect=OSError('offline')):
    with self.assertRaises(OSError):g.close()
   self.assertTrue(g.ready);self.assertIsNotNone(g.lock);g.ready=False;g.close()

class LearningPilotIntegrationTests(unittest.IsolatedAsyncioTestCase):
 async def test_actual_background_controller_and_two_restart_checkpoints_without_network(self):
  from tavi.conversation_providers import Speech
  store=Store();self.addCleanup(store.close)
  with tempfile.TemporaryDirectory() as tmp:
   folder=Path(tmp)
   class Gateway:
    def __init__(self,folder):self.active=False
    def start(self):self.active=True
    def close(self):self.active=False
   class Worker:
    def __init__(self,*args):self.closed=False
    def send(self,request,timeout=45):
     if request['op']=='query':return {'ok':True,'result':{'native_context':[],'retrieval_ms':0,'scopes_searched':[]}}
     return {'ok':True,'result':{'stored':True}}
    def stop(self):self.closed=True
    @property
    def process(self):return SimpleNamespace(poll=lambda:0)
   class Ref:
    def __init__(self,*args):pass
    async def connect(self):pass
    async def reply(self,*args):return {'text':'That sounds fun.','status':'completed'}
    async def close(self):pass
   class Voice:
    async def synthesize(self,text):return Speech(b'no-playback',100)
   with patch('experiments.memory.learning_pilot.require_ssd'),patch('experiments.memory.learning_pilot.begin',return_value=(folder,{})),patch('experiments.memory.learning_pilot.audit'),patch('experiments.memory.learning_pilot.LearningGateway',Gateway),patch('experiments.memory.pilot.Process',Worker),patch('experiments.memory.learning_pilot.NativeTextReference',Ref):
    p=LearningPilot(store);c=p.conversation(store,speech=Voice())
    # tiktoken asset is already available locally; avoid invoking its loader in
    # an isolated test and return a deterministic bounded test encoding.
    with patch('tiktoken.get_encoding',return_value=SimpleNamespace(encode=lambda value:list(value.encode()))):
     await p.prepare({'adult':True,'online':True,'record_audio':False,'pilot_consent':CONSENT})
    c.start('unit')
    async def turn(n,text):
     c.feed('unit',{'events':[{'type':'speech_started','utterance':n},{'type':'recognition','utterance':n,'text':text,'final':True,'recognition_id':str(n)}]})
     async with asyncio.timeout(3):
      while not c.audio:
       if c.failure:raise AssertionError(c.failure)
       await asyncio.sleep(.005)
      while c.completed_response_id!=c.controller.token.response_id:
       if c.audio:
        a=c.audio;body={'response_id':a['id'],'sequence':a['sequence']};c.command('unit','started',body);c.command('unit','played',body)
       await asyncio.sleep(.005)
    try:
     await turn(1,'Paprika, I enjoy wooden gliders.')
     for stage in [1,2]:
      async with asyncio.timeout(3):
       while not (await p.checkpoint(c,stage))['ready']:await asyncio.sleep(.005)
      self.assertEqual(c.history,[])
      if stage==1:
       await turn(2,'Paprika, what project could I make?')
       await turn(3,'I want stick bridges instead.')
     self.assertEqual(p.checkpoints,[1,2]);self.assertEqual(len(p.sources),3)
     self.assertIsNone(p.extra_state(c)['learning']['error']);p.persist(c)
     saved=json.loads((folder/'observations.json').read_text());self.assertTrue(saved['memory_writes']);self.assertEqual(len(saved['sources']),3)
     durable=saved['durable_learning_diagnostics'];self.assertEqual(durable['counts'],{'complete':3})
     self.assertEqual(sum(len(r['events']) for r in durable['sources']),12)
     self.assertTrue(all(r['timing_coverage']=='from_capture' for r in durable['sources']))
    finally:
     await c.close();await p.close(c)
    self.assertFalse(p.gateway.active)
