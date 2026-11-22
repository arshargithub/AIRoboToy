import asyncio
import unittest

from tavi.chunked_conversation import ChunkedConversation
from tavi.conversation_providers import Speech
from tavi.storage import Store


TEXT = 'A little turtle found a bright silver shell. It shared the treasure with a friendly whale. They made a tiny garden beneath the sea.'


class Voice:
    async def synthesize(self, text): return Speech(text.encode(), 1000)


class Brain:
    async def stream_reply(self, history): yield TEXT
    async def close(self): pass


class ChunkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = Store(); self.addCleanup(self.store.close)
        self.c = ChunkedConversation(self.store, provider=Brain(), speech=Voice())
        self.c.start('lease'); self.addAsyncCleanup(self.c.close)
    def request(self, text='Paprika, tell me a story', number=1):
        self.c.feed('lease', {'events':[
            {'type':'speech_started','utterance':number},
            {'type':'recognition','utterance':number,'text':text,'final':True,'first_detection':True}]})
    async def settle(self):
        for _ in range(30): await asyncio.sleep(0)
    def ack(self, kind, sequence, rid=None):
        return self.c.command('lease', kind, {'response_id':rid or self.c.controller.token.response_id,'sequence':sequence})

    async def test_order_duplicate_rejection_history_and_single_completion(self):
        self.request(); await self.settle()
        rid = self.c.controller.token.response_id
        self.assertEqual(len(self.c.chunks), 2)
        self.assertFalse(self.ack('played', 0), 'Cannot acknowledge unheard audio')
        self.assertFalse(self.ack('started', 1))
        self.assertTrue(self.ack('started', 0)); self.assertTrue(self.ack('played', 0))
        self.assertFalse(self.ack('played', 0)); await self.settle()
        self.assertEqual(self.c.snapshot()['audio']['sequence'], 1)
        self.assertTrue(self.ack('started', 1)); self.assertTrue(self.ack('played', 1)); await self.settle()
        self.assertTrue(self.ack('started', 2)); self.assertTrue(self.ack('played', 2)); await self.settle()
        self.assertEqual(self.c.snapshot()['completed_response_id'], rid)
        self.assertEqual(self.c.history[-1]['content'], TEXT)
        self.assertEqual(sum(m['kind']=='playback_completed' for m in self.c.metrics), 1)

    async def test_no_audio_before_complete_text_validation(self):
        release = asyncio.Event(); entered = asyncio.Event()
        class Pending(Brain):
            async def stream_reply(self, history):
                yield 'A little turtle found a bright silver shell. '
                entered.set(); await release.wait()
                yield 'It shared the treasure.'
        self.c.provider = Pending(); self.request(); await entered.wait(); await self.settle()
        self.assertIsNone(self.c.snapshot()['audio'])
        release.set(); await self.settle()
        self.assertIsNotNone(self.c.snapshot()['audio'])

    async def test_failed_terminal_discards_prepared_audio_and_labels_reasoning(self):
        class Failed(Brain):
            async def stream_reply(self, history):
                yield 'A little turtle found a bright silver shell. '
                await asyncio.sleep(0)
                raise ValueError('Missing completed text')
        self.c.provider = Failed(); self.request(); await self.settle()
        self.assertIsNone(self.c.snapshot()['audio'])
        self.assertEqual(self.c.failure['component'], 'reasoning')
        self.assertEqual(len(self.c.chunks), 0)

    async def test_interruption_clears_all_future_chunks_and_stale_acks(self):
        self.request(); await self.settle(); rid = self.c.controller.token.response_id
        self.assertTrue(self.ack('started', 0))
        self.assertTrue(self.c.command('lease','interrupt',{'response_id':rid}))
        await self.settle()
        self.assertIsNone(self.c.snapshot()['audio']); self.assertEqual(len(self.c.chunks), 0)
        self.assertFalse(self.ack('played',0,rid))
        with self.assertRaises(ValueError): self.c.audio_bytes('lease',rid,1)
        self.assertFalse(any(m['role']=='assistant' for m in self.c.history))

    async def test_goodbye_ends_only_after_final_playback(self):
        self.request('Paprika, goodbye'); await self.settle()
        rid = self.c.controller.token.response_id
        self.assertTrue(self.c.engaged)
        self.assertTrue(self.ack('started',0)); self.assertTrue(self.ack('played',0)); await self.settle()
        self.assertFalse(self.c.engaged)
        self.assertEqual(self.c.snapshot()['completed_response_id'],rid)

    async def test_voice_error_clears_queue_and_labels_speech(self):
        class Broken:
            async def synthesize(self,text): raise ValueError('Synthetic voice fault')
        self.c.speech=Broken(); self.request(); await self.settle()
        self.assertEqual(self.c.failure['component'],'speech')
        self.assertEqual(self.c.snapshot()['error'],'Local voice unavailable')
        self.assertEqual(self.c.failure['sequence'],0)
        self.assertIsNone(self.c.snapshot()['audio'])

    async def test_late_voice_error_preserves_only_played_prefix(self):
        release=asyncio.Event(); calls=[]
        class BrokenLater:
            async def synthesize(self,text):
                calls.append(text)
                if len(calls)==2:
                    await release.wait()
                    raise ValueError('Later chunk failed')
                return Speech(text.encode(),1000)
        self.c.speech=BrokenLater();self.request();await self.settle()
        self.assertTrue(self.ack('started',0));self.assertTrue(self.ack('played',0))
        release.set();await self.settle()
        self.assertIsNone(self.c.snapshot()['audio'])
        self.assertEqual(self.c.history[-1]['content'],calls[0])
        self.assertNotEqual(self.c.history[-1]['content'],TEXT)
        self.assertIsNone(self.c.snapshot()['completed_response_id'])

    async def test_mute_with_full_queue_reclaims_background_task(self):
        self.request();await self.settle();task=self.c.task
        self.assertEqual(len(self.c.chunks),2)
        self.c.stop();await self.settle()
        self.assertTrue(task.done())
        self.assertIsNone(self.c.snapshot()['audio'])
        self.assertFalse(self.c.snapshot()['lease_active'])


if __name__=='__main__': unittest.main()
