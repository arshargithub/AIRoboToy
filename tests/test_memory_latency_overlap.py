import asyncio
from copy import deepcopy
import unittest
from experiments.memory.native_text import NativeTextReference
from tests import test_memory_conversation as fixtures
TEXT=fixtures.TEXT

class OverlapTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.MemoryConversationTests.asyncSetUp
    request=fixtures.MemoryConversationTests.request
    settle=fixtures.MemoryConversationTests.settle
    async def test_connection_and_lookup_start_together_but_no_early_request(self):
        entered=asyncio.Event();release=asyncio.Event();factory=self.provider.reference_factory
        class Ref(factory):
            async def connect(self):entered.set();await release.wait()
        self.provider.reference_factory=Ref;self.lookup_gate=asyncio.Event()
        self.request();await asyncio.wait_for(entered.wait(),1);await self.settle()
        self.assertEqual(len(self.lookup_calls),1);self.assertEqual(self.calls,[])
        self.lookup_gate.set();await self.settle();self.assertEqual(self.calls,[])
        release.set();await self.settle();self.assertEqual(len(self.calls),1)

    async def test_lookup_error_cancels_connect_and_closes_without_inference(self):
        factory=self.provider.reference_factory;cancelled=asyncio.Event()
        class Ref(factory):
            async def connect(self):
                try:await asyncio.Event().wait()
                finally:cancelled.set()
        async def fail(task):raise ValueError('lookup failed')
        self.provider.reference_factory=Ref;self.provider.recall=fail
        self.request();await self.settle()
        self.assertTrue(cancelled.is_set());self.assertTrue(self.refs[0].closed)
        self.assertEqual(self.calls,[]);self.assertIsNone(self.c.audio)

    async def native(self,mode='good'):
        owner=self;self.release=asyncio.Event()
        class Ref(NativeTextReference):
            async def connect(self):self.closed=False;self.index=0;owner.refs.append(self)
            async def send(self,*args,**kwargs):self.case=kwargs['response']['metadata']['case_id'];owner.calls.append(kwargs)
            async def receive(self):
                self.index+=1
                if self.index==1:return {'type':'response.created','response':{'id':'r','metadata':{'case_id':self.case}}}
                if self.index==2:return {'type':'response.output_text.delta','response_id':'r','delta':TEXT}
                await owner.release.wait()
                text=TEXT if mode!='mismatch' else 'Wrong terminal text.'
                return {'type':'response.done','response':{'id':'r','status':'cancelled' if mode=='cancelled' else 'completed','usage':{'input_tokens':1,'output_tokens':1},'output':[{'content':[{'type':'output_text','text':text}]}]}}
            async def close(self):self.closed=True
        self.provider.reference_factory=Ref;self.request();await self.settle()

    async def test_real_native_deltas_prepare_voice_privately_until_terminal(self):
        await self.native()
        self.assertTrue(self.voiced);self.assertIsNone(self.c.audio)
        self.assertFalse(any(x['role']=='assistant' for x in self.c.history))
        self.release.set();await self.settle()
        self.assertIsNotNone(self.c.audio);self.assertTrue(self.refs[0].closed)
        self.assertEqual(self.c.last_reply,TEXT)
        self.assertTrue(self.provider.observations[-1]['completed'])

    async def test_terminal_mismatch_discards_prepared_audio(self):
        await self.native('mismatch');self.assertTrue(self.voiced)
        self.release.set();await self.settle()
        self.assertIsNone(self.c.audio);self.assertEqual(list(self.c.chunks),[])
        self.assertFalse(any(x['role']=='assistant' for x in self.c.history))
        self.assertTrue(self.refs[0].closed)

    async def test_cancelled_terminal_discards_prepared_audio(self):
        await self.native('cancelled');self.release.set();await self.settle()
        self.assertIsNone(self.c.audio);self.assertTrue(self.refs[0].closed)

    async def test_new_scope_discards_private_native_audio_and_history(self):
        await self.native();self.scope['revision']+=1
        self.release.set();await self.settle()
        self.assertIsNone(self.c.audio);self.assertEqual(self.c.history,[])
        self.assertTrue(self.refs[0].closed)

    async def test_interrupt_before_terminal_closes_stream_without_publication(self):
        await self.native();rid=self.c.controller.token.response_id
        self.c.command('lease','interrupt',{'response_id':rid});await self.settle()
        self.assertIsNone(self.c.audio);self.assertTrue(self.refs[0].closed)
        self.assertEqual(len(self.calls),1)
