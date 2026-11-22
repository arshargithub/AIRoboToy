import asyncio
from copy import deepcopy
import unittest

from experiments.memory.conversation_adapter import MemoryTextProvider
from tavi.chunked_conversation import ChunkedConversation
from tavi.conversation_providers import Speech
from tavi.storage import Store

TEXT = 'We could fold a bright green paper animal. Then we could make a tiny home for it. Would you like a fox or a turtle?'

class MemoryConversationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store=Store();self.addCleanup(self.store.close)
        self.scope={'revision':1,'task':{'people':{'a':'Nora','b':'Theo'},
            'actual_speaker_id':'a','audience_ids':['a'],'conversation_at':'2026-11-05T12:00:00Z'}}
        self.calls=[];self.voiced=[];self.refs=[];self.lookup_calls=[]
        self.lookup_gate=None;self.reply_gate=None;self.voice_gate=None;self.fail_voice_at=None
        owner=self
        class Reference:
            def __init__(self,store):self.closed=False;owner.refs.append(self)
            async def connect(self):pass
            async def reply(self,task,evidence,case_id):
                owner.calls.append(deepcopy((task,evidence)))
                if owner.reply_gate:await owner.reply_gate.wait()
                return {'text':TEXT,'status':'completed'}
            async def close(self):self.closed=True
        class Voice:
            async def synthesize(self,text):
                owner.voiced.append(text)
                if owner.voice_gate:await owner.voice_gate.wait()
                if len(owner.voiced)==owner.fail_voice_at:raise ValueError('voice failed')
                return Speech(text.encode(),1000)
        async def recall(task):
            owner.lookup_calls.append(task)
            if owner.lookup_gate:await owner.lookup_gate.wait()
            return {'evidence':{'facts':[]},'sources':[]}
        self.provider=MemoryTextProvider(self.store,scope=lambda:self.scope,recall=recall,reference_factory=Reference)
        self.c=ChunkedConversation(self.store,provider=self.provider,speech=Voice(),context_revision=lambda:self.scope)
        self.c.start('lease');self.addAsyncCleanup(self.c.close)

    def request(self,text='Paprika, what shall we make?',number=1):
        self.c.feed('lease',{'events':[{'type':'speech_started','utterance':number},
            {'type':'recognition','utterance':number,'text':text,'final':True}]})
    async def settle(self):
        for _ in range(50):await asyncio.sleep(0)
    def ack(self,command,audio):
        return self.c.command('lease',command,{'response_id':audio['id'],'sequence':audio['sequence']})

    async def test_diagnostics_describe_actual_provider_without_starting_inference(self):
        from tavi.realtime_reference import MODEL
        state=self.c.snapshot()
        self.assertEqual(state['model'],MODEL);self.assertTrue(state['memory_enabled'])
        self.assertEqual(self.calls,[]);self.assertEqual(self.lookup_calls,[])

    async def test_unengaged_and_stop_do_not_lookup_or_open_cloud(self):
        self.request('What shall we make?');await self.settle()
        self.assertEqual(self.lookup_calls,[])
        self.request('Paprika, stop.',2);await self.settle()
        self.assertEqual(self.refs,[]);self.assertEqual(self.lookup_calls,[])

    async def test_unknown_identity_rejected_before_lookup(self):
        self.scope['task']['actual_speaker_id']='unknown'
        self.request();await self.settle()
        self.assertEqual(self.lookup_calls,[]);self.assertEqual(self.refs,[])
        self.assertEqual(self.c.failure['component'],'reasoning')

    async def test_cancelled_lookup_closes_speculative_connection_without_inference(self):
        self.lookup_gate=asyncio.Event();self.request();await self.settle()
        old=self.c.controller.token.response_id
        self.c.command('lease','interrupt',{'response_id':old})
        self.lookup_gate.set();await self.settle()
        self.assertTrue(self.refs[0].closed);self.assertEqual(self.calls,[]);self.assertIsNone(self.c.audio)

    async def test_audience_change_during_reply_cancels_and_closes(self):
        self.reply_gate=asyncio.Event();self.request();await self.settle()
        self.scope['task']['audience_ids'].append('b')
        self.assertIsNone(self.c.snapshot()['audio'])
        self.reply_gate.set();await self.settle()
        self.assertEqual(self.voiced,[]);self.assertTrue(self.refs[0].closed)
        self.assertEqual(self.c.history,[])

    async def test_completion_barrier_then_scope_change_during_voice(self):
        self.reply_gate=asyncio.Event();self.request();await self.settle()
        self.assertEqual(self.voiced,[])
        self.voice_gate=asyncio.Event();self.reply_gate.set();await self.settle()
        self.assertTrue(self.refs[0].closed)
        self.scope['revision']+=1;self.voice_gate.set();await self.settle()
        self.assertIsNone(self.c.snapshot()['audio']);self.assertEqual(self.c.history,[])

    async def test_scope_change_blocks_queued_fetch_and_ack(self):
        self.request();await self.settle();a=dict(self.c.audio)
        self.scope['revision']+=1
        with self.assertRaises(ValueError):self.c.audio_bytes('lease',a['id'],a['sequence'])
        self.assertFalse(self.ack('started',a));self.assertEqual(self.c.history,[])

    async def test_interrupted_history_contains_only_completed_chunks(self):
        self.request();await self.settle();a=dict(self.c.audio)
        self.assertTrue(self.ack('started',a));self.assertTrue(self.ack('played',a))
        await self.settle();b=dict(self.c.audio);self.assertTrue(self.ack('started',b))
        self.c.command('lease','interrupt',{'response_id':b['id']})
        await self.settle()
        self.assertEqual(self.c.history[-1]['content'],a['text'])
        self.assertFalse(self.ack('played',b))
        self.request('Can we make it blue?',2);await self.settle()
        history=self.calls[-1][0]['recent_conversation']
        self.assertEqual(history[-1],{'role':'assistant','content':a['text']})
        self.assertEqual(self.calls[-1][0]['question'],'Can we make it blue?')

    async def test_scope_changes_before_response_task_starts(self):
        self.request()
        self.scope['task']['actual_speaker_id']='b'
        await self.settle()
        self.assertEqual(self.calls,[]);self.assertEqual(self.lookup_calls,[])
        self.assertEqual(self.c.history,[])

    async def test_scope_change_during_lookup_without_poll_still_retires_history(self):
        self.lookup_gate=asyncio.Event();self.request();await self.settle()
        self.scope['revision']+=1;self.lookup_gate.set();await self.settle()
        self.assertTrue(self.refs[0].closed);self.assertEqual(self.calls,[]);self.assertEqual(self.c.history,[])

    async def test_slow_connection_close_does_not_hold_completed_audio(self):
        release=asyncio.Event();factory=self.provider.reference_factory
        class SlowClose(factory):
            async def close(self):
                await release.wait()
                await super().close()
        self.provider.reference_factory=SlowClose
        try:
            self.request();await self.settle()
            self.assertIsNotNone(self.c.audio)
            self.assertFalse(self.refs[0].closed)
            self.assertEqual(len(self.provider.cleanup),1)
        finally:
            release.set();await self.settle()
        self.assertTrue(self.refs[0].closed)
        self.assertFalse(self.provider.active)

    async def test_voice_failure_does_not_retry_or_remember_unheard_text(self):
        self.fail_voice_at=1;self.request();await self.settle()
        self.assertEqual(len(self.calls),1);self.assertTrue(self.refs[0].closed)
        self.assertFalse(any(m['role']=='assistant' for m in self.c.history))
        self.assertEqual(self.c.failure['component'],'speech')

    async def test_new_speaker_between_completed_turns_cannot_receive_previous_private_history(self):
        self.request('Paprika, my private project is a paper dragon.');await self.settle()
        while self.c.audio:
            a=dict(self.c.audio);self.ack('started',a);self.ack('played',a);await self.settle()
        self.assertTrue(any('private project' in m['content'] for m in self.c.history))
        # No snapshot/poll occurs after the host changes the trusted identity.
        # Final input acceptance must guard history even without a UI read.
        self.scope['task']['actual_speaker_id']='b';self.scope['task']['audience_ids']=['b']
        self.request('What could we make?',2);await self.settle()
        self.assertEqual(self.calls[-1][0]['recent_conversation'],[])
        self.assertEqual(self.calls[-1][0]['actual_speaker_id'],'b')

    async def test_new_audience_between_turns_cannot_receive_previous_private_history(self):
        self.request('Paprika, a private idea for me alone.');await self.settle()
        while self.c.audio:
            a=dict(self.c.audio);self.ack('started',a);self.ack('played',a);await self.settle()
        self.scope['task']['audience_ids'].append('b')
        self.request('What could we make?',2);await self.settle()
        self.assertEqual(self.calls[-1][0]['recent_conversation'],[])

    async def test_timestamp_change_alone_preserves_same_person_followup_history(self):
        self.request('Paprika, let us make a paper dragon.');await self.settle()
        while self.c.audio:
            a=dict(self.c.audio);self.ack('started',a);self.ack('played',a);await self.settle()
        self.scope['task']['conversation_at']='2026-11-05T12:01:00Z'
        self.request('Make it blue please.',2);await self.settle()
        self.assertIn('paper dragon',str(self.calls[-1][0]['recent_conversation']))

if __name__=='__main__':unittest.main()
