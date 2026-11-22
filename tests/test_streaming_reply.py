import asyncio
from io import BytesIO
from types import SimpleNamespace as NS
import unittest
import wave

from tavi.conversation_providers import PaidText
from tavi.benchmark_reply_overlap import overlap
from tavi.conversation_providers import Speech
from tavi.sentence_chunks import SentenceChunks
from tavi.storage import Store, APPROVED_BUDGET_MICRO_USD


class Stream:
    def __init__(self, events, hold=False):
        self.events = iter(events)
        self.closed = False
        self.hold = hold
    def __aiter__(self): return self
    async def __anext__(self):
        if self.hold: await asyncio.Event().wait()
        try: return next(self.events)
        except StopIteration: raise StopAsyncIteration
    async def close(self): self.closed = True


class StreamingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = Store()
        self.addCleanup(self.store.close)
        self.calls = []
    def provider(self, stream):
        async def create(**kwargs):
            self.assertEqual(self.store.used_micro_usd(), 50000)
            self.calls.append(kwargs)
            return stream
        return PaidText(self.store, NS(responses=NS(create=create)))
    def terminal(self, text):
        return NS(type='response.completed', response=NS(status='completed', output_text=text,
                  usage=NS(input_tokens=100, output_tokens=20)))

    async def test_completion_preserves_exact_text_settles_and_closes(self):
        stream = Stream([NS(type='response.output_text.delta', delta='A little '),
                         NS(type='response.output_text.delta', delta='rocket.'), self.terminal('A little rocket.')])
        provider = self.provider(stream)
        self.assertEqual(''.join([s async for s in provider.stream_reply([{'role':'user','content':'A story'}])]), 'A little rocket.')
        self.assertEqual(self.store.used_micro_usd(), 165)
        self.assertEqual(provider.completed, 1)
        self.assertTrue(stream.closed)
        self.assertTrue(self.calls[0]['stream'])
        self.assertFalse(self.calls[0]['store'])
        self.assertEqual(self.calls[0]['tools'], [])

    async def test_missing_terminal_or_failure_keeps_reservation_without_retry(self):
        for events in ([], [NS(type='response.failed')]):
            stream = Stream(events)
            provider = self.provider(stream)
            with self.assertRaises(ValueError):
                _ = [s async for s in provider.stream_reply([{'role':'user','content':'A story'}])]
            self.assertTrue(stream.closed)
            self.assertEqual(provider.completed, 0)
            self.assertEqual(len(self.calls), 1)
            self.assertEqual(self.store.used_micro_usd(), 50000)
            self.store.close(); self.store = Store(); self.addCleanup(self.store.close); self.calls.clear()

    async def test_cancel_closes_transport_retains_reservation(self):
        stream = Stream([], hold=True)
        provider = self.provider(stream)
        async def consume():
            return [s async for s in provider.stream_reply([{'role':'user','content':'A story'}])]
        task = asyncio.create_task(consume())
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertTrue(stream.closed)
        self.assertEqual(self.store.used_micro_usd(), 50000)

    async def test_inconsistent_final_or_oversized_prefix_never_succeeds(self):
        for delta, terminal in [('A rocket.', 'A boat.'), ('x'*481, 'x'*481)]:
            stream = Stream([NS(type='response.output_text.delta', delta=delta), self.terminal(terminal)])
            provider = self.provider(stream)
            with self.assertRaises(ValueError):
                _ = [s async for s in provider.stream_reply([{'role':'user','content':'A story'}])]
            self.assertEqual(provider.completed, 0)
            self.assertTrue(stream.closed)
            self.store.close(); self.store = Store(); self.addCleanup(self.store.close); self.calls.clear()

    async def test_exhausted_budget_sends_nothing(self):
        self.store.reserve('earlier', APPROVED_BUDGET_MICRO_USD, APPROVED_BUDGET_MICRO_USD)
        with self.assertRaises(ValueError):
            _ = [s async for s in self.provider(Stream([])).stream_reply([{'role':'user','content':'A story'}])]
        self.assertEqual(self.calls, [])

    async def test_drain_rejects_post_completion_delta_and_does_not_count_success(self):
        stream=Stream([NS(type='response.output_text.delta',delta='A rocket.'),self.terminal('A rocket.'),
                       NS(type='response.output_text.delta',delta=' Unexpected.')])
        provider=self.provider(stream);provider.drain_stream=True
        with self.assertRaisesRegex(ValueError,'after completed'):
            _=[s async for s in provider.stream_reply([{'role':'user','content':'A story'}])]
        self.assertEqual(provider.completed,0)
        self.assertTrue(stream.closed)

    async def test_drain_waits_for_eof_before_success_and_can_be_cancelled(self):
        reached_eof=asyncio.Event()
        class HeldTail(Stream):
            async def __anext__(self):
                try:return next(self.events)
                except StopIteration:
                    reached_eof.set();await asyncio.Event().wait()
        stream=HeldTail([NS(type='response.output_text.delta',delta='A rocket.'),self.terminal('A rocket.')])
        provider=self.provider(stream);provider.drain_stream=True
        async def consume():return [s async for s in provider.stream_reply([{'role':'user','content':'A story'}])]
        task=asyncio.create_task(consume());await reached_eof.wait()
        self.assertEqual(provider.completed,0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(stream.closed)


class SentenceTests(unittest.TestCase):
    def test_every_token_boundary_preserves_text(self):
        text = 'Ready? A little turtle met Dr. Smith at 3.5 o’clock. They found a bright shell!'
        for size in range(1, len(text)):
            splitter = SentenceChunks(); chunks = []
            for start in range(0, len(text), size): chunks.extend(splitter.feed(text[start:start+size]))
            chunks.extend(splitter.finish())
            self.assertEqual(''.join(chunks), text)
            self.assertFalse(chunks[0].strip() == 'Ready?')
            self.assertFalse(any(c.rstrip().endswith('Dr.') for c in chunks))
            self.assertFalse(any(c.rstrip().endswith('3.') for c in chunks))


class OverlapTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_stops_both_stream_and_inflight_synthesis(self):
        entered = asyncio.Event(); closed = []; cancelled = []
        class Provider:
            async def stream_reply(self, history):
                try:
                    yield 'A little turtle found a very bright shell. '
                    await asyncio.Event().wait()
                finally: closed.append(True)
        class Voice:
            async def synthesize(self, text):
                entered.set()
                try: await asyncio.Event().wait()
                finally: cancelled.append(True)
        task = asyncio.create_task(overlap(Provider(), Voice(), []))
        await entered.wait(); task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertEqual(closed, [True]); self.assertEqual(cancelled, [True])

    async def test_success_preserves_all_text_and_combined_audio_order(self):
        text = 'A little turtle found a very bright shell. It shared the treasure with a friendly whale.'
        calls = []
        class Provider:
            async def stream_reply(self, history):
                for offset in range(0, len(text), 5):
                    yield text[offset:offset+5]
                    await asyncio.sleep(0)
        class Voice:
            async def synthesize(self, chunk):
                calls.append(chunk); output = BytesIO()
                with wave.open(output, 'wb') as target:
                    target.setnchannels(1); target.setsampwidth(2); target.setframerate(24000)
                    target.writeframes(int(len(calls)).to_bytes(2, 'little', signed=True)*240)
                return Speech(output.getvalue(), 10)
        result, audio = await overlap(Provider(), Voice(), [])
        self.assertEqual(''.join(calls), text)
        self.assertEqual(result['text'], text)
        with wave.open(BytesIO(audio.wav)) as source:
            data = source.readframes(source.getnframes())
        self.assertEqual(data, b'\x01\x00'*240+b'\x02\x00'*240)

    async def test_terminal_failure_cancels_voice_and_publishes_no_audio(self):
        entered = asyncio.Event(); stopped = []
        class Provider:
            async def stream_reply(self, history):
                yield 'A little turtle found a very bright shell. '
                await entered.wait()
                raise ValueError('Missing completion')
        class Voice:
            async def synthesize(self, text):
                entered.set()
                try: await asyncio.Event().wait()
                finally: stopped.append(True)
        with self.assertRaises(ExceptionGroup): await overlap(Provider(), Voice(), [])
        self.assertEqual(stopped, [True])


if __name__ == '__main__': unittest.main()
