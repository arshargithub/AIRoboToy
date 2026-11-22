import asyncio
import time
import unittest

from tavi.inference_schedule import ScheduledSpeech


class Speech:
    name = 'Synthetic local voice'

    def __init__(self):
        self.started = asyncio.Queue()
        self.finish = asyncio.Event()
        self.calls = []
        self.cancelled = 0

    async def prepare(self): pass
    async def close(self): pass

    async def synthesize(self, text):
        self.calls.append(text)
        self.started.put_nowait(text)
        try:
            await self.finish.wait()
            return b'complete WAV'
        except asyncio.CancelledError:
            await asyncio.sleep(0)  # Native cleanup must finish before ASR.
            self.cancelled += 1
            raise


class ScheduleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.voice = Speech()
        self.schedule = ScheduledSpeech(self.voice, asyncio.get_running_loop())
        self.addAsyncCleanup(self.schedule.close)

    async def test_final_preempts_native_work_and_resumes_same_text_after_all_holds(self):
        reply = asyncio.create_task(self.schedule.synthesize('Preserve this reply.'))
        await self.voice.started.get()
        await self.schedule.acquire_asr('first')
        self.assertEqual(self.voice.cancelled, 1, 'ASR waits for native cleanup')
        await self.schedule.acquire_asr('second')
        await self.schedule.release_asr('first')
        await asyncio.sleep(0)
        self.assertEqual(len(self.voice.calls), 1)
        await self.schedule.release_asr('second')
        await self.voice.started.get()
        self.voice.finish.set()
        self.assertEqual(await reply, b'complete WAV')
        self.assertEqual(self.voice.calls, ['Preserve this reply.']*2)

    async def test_obsolete_reply_never_resumes_after_caller_cancellation(self):
        reply = asyncio.create_task(self.schedule.synthesize('Obsolete.'))
        await self.voice.started.get()
        await self.schedule.acquire_asr('final')
        reply.cancel()
        with self.assertRaises(asyncio.CancelledError): await reply
        await self.schedule.release_asr('final')
        await asyncio.sleep(0)
        self.assertEqual(self.voice.calls, ['Obsolete.'])

    async def test_sync_bridge_releases_hold_after_native_timeout(self):
        def decode():
            with self.schedule.final_asr(time.monotonic()+1):
                raise TimeoutError('Synthetic native deadline')
        with self.assertRaises(TimeoutError): await asyncio.to_thread(decode)
        await asyncio.sleep(0)
        self.assertFalse(self.schedule.holds)
        self.voice.finish.set()
        self.assertEqual(await self.schedule.synthesize('Fresh.'), b'complete WAV')

    async def test_repeated_noise_cannot_retry_one_chunk_without_bound(self):
        reply=asyncio.create_task(self.schedule.synthesize('One local chunk.'))
        for n in range(3):
            await self.voice.started.get()
            await self.schedule.acquire_asr(str(n))
            await self.schedule.release_asr(str(n))
        with self.assertRaisesRegex(ValueError,'preemption bound'):await reply
        self.assertEqual(len(self.voice.calls),3)


if __name__ == '__main__': unittest.main()
