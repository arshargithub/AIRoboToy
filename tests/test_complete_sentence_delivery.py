import asyncio
import unittest
from tavi.chunked_conversation import ChunkedConversation
from tavi.sentence_chunks import SentenceChunks
from tavi.conversation_providers import Speech
from tavi.storage import Store

class CompleteSentenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_short_substantive_sentence_kept_and_terminal_barrier_preserved(self):
        text='I would pick Maple Mystery. It has funny clues and gentle stakes.'
        release=asyncio.Event();entered=asyncio.Event();parts=[]
        class Brain:
            async def stream_reply(self,history):
                yield text;entered.set();await release.wait()
            async def close(self):pass
        class Voice:
            async def synthesize(self,part):parts.append(part);return Speech(part.encode(),1000)
        store=Store();self.addCleanup(store.close)
        c=ChunkedConversation(store,provider=Brain(),speech=Voice(),sentence_minimum=1)
        self.addAsyncCleanup(c.close);c.start('test')
        c.feed('test',{'events':[{'type':'speech_started','utterance':1},{'type':'recognition','utterance':1,'text':'Paprika, suggest a book.','final':True}]})
        await entered.wait()
        for _ in range(10):await asyncio.sleep(0)
        self.assertIsNone(c.snapshot()['audio'])
        release.set();await c.task
        self.assertEqual(parts,['I would pick Maple Mystery. ','It has funny clues and gentle stakes.'])
        self.assertEqual(''.join(parts),text)
        self.assertEqual(c.history,[{'role':'user','content':'Paprika, suggest a book.'}])

    def test_abbreviations_decimals_and_quotes_are_preserved(self):
        for text in ['Dr. Fox found 3.5 shells. Then he rested.', '“Yes!” she said. A. B. Fox waved.', 'Hi. How are you?']:
            s=SentenceChunks(minimum=1);parts=s.feed(text)+s.finish()
            self.assertEqual(''.join(parts),text)
            self.assertFalse(any(p.strip() in ('Dr.','A.','B.','3.') for p in parts))

    def test_default_remains_unchanged_and_invalid_options_rejected(self):
        store=Store();self.addCleanup(store.close)
        self.assertEqual(ChunkedConversation(store).sentence_minimum,32)
        for value in [0,33,True,1.0]:
            with self.assertRaises(ValueError):ChunkedConversation(store,sentence_minimum=value)

    async def test_memory_preset_short_sentence_and_changed_scope_invalidates_audio(self):
        from experiments.memory.conversation_adapter import make_conversation
        scope={'revision':1,'task':{'people':{'a':'Nora'},'actual_speaker_id':'a','audience_ids':['a']}}
        calls=[];voiced=[]
        async def recall(task):return {'evidence':{'facts':[]},'sources':[]}
        class Reference:
            def __init__(self,store):calls.append(store)
            async def connect(self):pass
            async def reply(self,*args):return {'status':'completed','text':'Try Maple Mystery. It has gentle clues.'}
            async def close(self):pass
        class Voice:
            async def synthesize(self,text):voiced.append(text);return Speech(text.encode(),1000)
            async def close(self):pass
        store=Store();self.addCleanup(store.close);budget=object()
        c=make_conversation(store,scope=lambda:scope,recall=recall,speech=Voice(),provider_store=budget,reference_factory=Reference)
        self.addAsyncCleanup(c.close);c.start('test')
        c.feed('test',{'events':[{'type':'speech_started','utterance':1},{'type':'recognition','utterance':1,'text':'Paprika, suggest a book.','final':True}]})
        await c.task
        self.assertEqual(calls,[budget]);self.assertEqual(voiced,['Try Maple Mystery. ','It has gentle clues.'])
        self.assertIsNotNone(c.snapshot()['audio'])
        scope['revision']=2
        self.assertIsNone(c.snapshot()['audio']);self.assertEqual(c.history,[])
