import asyncio
import unittest
from tests import test_chunked_conversation as fixtures

class PrefetchTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.ChunkTests.asyncSetUp
    request=fixtures.ChunkTests.request
    settle=fixtures.ChunkTests.settle
    async def test_fetch_does_not_advance_or_ack_future_chunk(self):
        self.request();await self.settle()
        first=self.c.snapshot()['audio'];next_audio=self.c.snapshot()['prefetch_audio']
        self.assertEqual(next_audio['sequence'],1)
        data=self.c.audio_bytes('lease',first['id'],1)
        self.assertEqual(data,self.c.chunks[1]['wav'])
        self.assertFalse(self.c.command('lease','started',{'response_id':first['id'],'sequence':1}))
        self.assertFalse(self.c.command('lease','played',{'response_id':first['id'],'sequence':1}))
        self.assertFalse(any(x['role']=='assistant' for x in self.c.history))
        self.c.command('lease','interrupt',{'response_id':first['id']})
        with self.assertRaises(ValueError):self.c.audio_bytes('lease',first['id'],1)
        self.assertIsNone(self.c.snapshot()['prefetch_audio'])

    async def test_new_input_hides_next_chunk(self):
        self.request();await self.settle();self.assertIsNotNone(self.c.snapshot()['prefetch_audio'])
        self.c.feed('lease',{'events':[{'type':'speech_started','utterance':2}]})
        self.assertIsNone(self.c.snapshot()['prefetch_audio'])
