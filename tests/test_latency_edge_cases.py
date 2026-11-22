import asyncio
import unittest
from tests import test_memory_conversation as memory_fixtures
from tavi.chunked_conversation import ChunkedConversation
from tavi.conversation_providers import Speech
from tavi.storage import Store

class LatencyEdges(unittest.IsolatedAsyncioTestCase):
    async def test_many_short_sentences_cannot_deadlock_terminal_validation(self):
        text='Hi! '*30;voiced=[]
        class Brain:
            async def stream_reply(self,history):yield text
            async def close(self):pass
        class Voice:
            async def synthesize(self,text):voiced.append(text);return Speech(text.encode(),100)
        store=Store();self.addCleanup(store.close)
        c=ChunkedConversation(store,provider=Brain(),speech=Voice(),sentence_minimum=1)
        self.addAsyncCleanup(c.close);c.start('lease')
        c.feed('lease',{'events':[{'type':'speech_started','utterance':1},{'type':'recognition','utterance':1,'final':True,'text':'Paprika, say hello.'}]})
        async with asyncio.timeout(1):
            while c.completed_response_id is None:
                if c.audio:
                    a=c.audio;body={'response_id':a['id'],'sequence':a['sequence']}
                    self.assertTrue(c.command('lease','started',body));self.assertTrue(c.command('lease','played',body))
                await asyncio.sleep(0)
        self.assertEqual(''.join(voiced),text);self.assertEqual(c.history[-1]['content'],text)
