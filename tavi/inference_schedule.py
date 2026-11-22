"""Final-ASR priority over restartable local speech, on the controller loop.

Only unfinished local synthesis is retried. Provider work, published WAVs and
conversation tokens are untouched. Caller cancellation always wins over resume.
"""
import asyncio
from contextlib import contextmanager
import time
from uuid import uuid4


class ScheduledSpeech:
    def __init__(self, speech, loop):
        self.speech, self.loop = speech, loop
        self.name = speech.name
        self.condition = asyncio.Condition()
        self.serial = asyncio.Lock()
        self.holds = set()
        self.active = None
        self.closed = False
        self.metrics = {'asr_holds': 0, 'synthesis_preemptions': 0,
                        'synthesis_resumes': 0, 'max_release_ms': 0}

    async def prepare(self):
        async with self.serial:
            await self.speech.prepare()

    async def synthesize(self, text):
        async with self.serial:
            resumed = 0
            deadline = time.monotonic()+20
            while True:
                async with self.condition:
                    await asyncio.wait_for(self.condition.wait_for(lambda: self.closed or not self.holds),
                                           max(0,deadline-time.monotonic()))
                    if self.closed:
                        raise asyncio.CancelledError
                    call = {'task': asyncio.create_task(self.speech.synthesize(text)),
                            'preempted': False}
                    self.active = call
                    if resumed:
                        self.metrics['synthesis_resumes'] += 1
                try:
                    return await asyncio.wait_for(call['task'],max(0,deadline-time.monotonic()))
                except asyncio.CancelledError:
                    if asyncio.current_task().cancelling() or not call['preempted']:
                        raise
                    resumed += 1
                    if resumed > 2:
                        raise ValueError('Local speech exceeded its preemption bound')
                finally:
                    async with self.condition:
                        if self.active is call:
                            self.active = None
                        self.condition.notify_all()

    async def acquire_asr(self, token):
        began = time.monotonic()
        async with self.condition:
            if self.closed:
                raise RuntimeError('Local inference scheduler closed')
            self.holds.add(token)
            self.metrics['asr_holds'] += 1
            call = self.active
            if call and not call['task'].done():
                call['preempted'] = True
                self.metrics['synthesis_preemptions'] += 1
                call['task'].cancel()
        # LocalSpeech cancellation kills AND reaps the native process. Do not
        # start ASR merely because cancellation was requested.
        if call:
            await asyncio.shield(asyncio.gather(call['task'], return_exceptions=True))
        self.metrics['max_release_ms'] = max(self.metrics['max_release_ms'],
                                             (time.monotonic()-began)*1000)

    async def release_asr(self, token):
        async with self.condition:
            self.holds.discard(token)
            self.condition.notify_all()

    @contextmanager
    def final_asr(self, deadline):
        """Synchronous recognizer-thread bridge; never called on its own loop."""
        token = uuid4().hex
        future = asyncio.run_coroutine_threadsafe(self.acquire_asr(token), self.loop)
        try:
            future.result(timeout=max(0, deadline-time.monotonic()))
            yield
        finally:
            # Even timeout/cancellation before acquire completes must release
            # the same hold. FIFO loop submission preserves acquire/release.
            future.cancel()
            asyncio.run_coroutine_threadsafe(self.release_asr(token), self.loop)

    async def close(self):
        async with self.condition:
            self.closed = True
            if self.active:
                self.active['task'].cancel()
            self.condition.notify_all()
        async with self.serial:
            await self.speech.close()
