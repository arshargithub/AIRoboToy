"""Opt-in memory provider for the existing sentence conversation controller.

Trusted scope and recall are injected by the local host. No voice identity is
inferred here. Live robot defaults do not select this experimental adapter.
"""
import asyncio
from collections import deque
from contextlib import aclosing
from copy import deepcopy
import time
from uuid import uuid4

from experiments.memory.native_text import NativeTextReference
from experiments.memory.reply_boundary import qualify_context
from tavi.realtime_reference import MODEL as NATIVE_MODEL


class MemoryTextProvider:
    model = NATIVE_MODEL
    memory_enabled = True
    def __init__(self, store, *, scope, recall, reference_factory=NativeTextReference,
                 evidence_qualifier=qualify_context):
        self.store, self.scope, self.recall = store, scope, recall
        self.reference_factory = reference_factory
        # Trusted-host opt-in only; model content never selects a qualifier.
        # Existing callers keep the original boundary until separately qualified.
        self.evidence_qualifier = evidence_qualifier
        self.active = set()
        self.cleanup = set()
        self.observations = deque(maxlen=16)
        self.closed = False

    async def stream_reply(self, history):
        if self.closed: raise ValueError('Memory provider closed')
        # All turns on this seam are already engaged by Conversation. Immediate
        # stop/goodbye/offline replies bypass this provider in that controller.
        issued = deepcopy(self.scope())
        task = deepcopy(issued['task'])
        if not history or history[-1]['role'] != 'user':
            raise ValueError('Missing current user request')
        task['question'] = history[-1]['content']
        task['recent_conversation'] = deepcopy(history[:-1][-11:])
        # Reject an unknown identity/audience before touching a personal bank.
        self.evidence_qualifier(task, {'facts': []}, [])

        def current():
            if self.closed or self.scope() != issued:
                raise ValueError('Memory scope changed')

        ref = None
        work = []
        row = {'id': uuid4().hex, 'task': task, 'completed': False}
        self.observations.append(row)
        start = time.monotonic()
        try:
            async with asyncio.timeout(55):
                # Start only after local engagement and trusted-scope checks.
                # No personal context or inference request is sent by connect().
                if len(self.cleanup) >= 2:
                    await asyncio.wait(self.cleanup, return_when=asyncio.FIRST_COMPLETED)
                current()
                ref = self.reference_factory(self.store)
                self.active.add(ref)
                async def connect():
                    t = time.monotonic()
                    await ref.connect()
                    current()
                    row['connection_ms'] = (time.monotonic()-t)*1000
                async def retrieve():
                    t = time.monotonic()
                    raw = await self.recall(deepcopy(task))
                    current()
                    row['boundary'] = self.evidence_qualifier(task, raw['evidence'], raw['sources'])
                    row['context_ms'] = (time.monotonic()-t)*1000
                work = [asyncio.create_task(connect()), asyncio.create_task(retrieve())]
                await asyncio.gather(*work)
                current()
                boundary = row['boundary']
                streamed = ''
                if hasattr(ref, 'stream_text'):
                    async with aclosing(ref.stream_text(task, boundary['evidence'], row['id'])) as deltas:
                        async for delta in deltas:
                            current()
                            streamed += delta
                            if len(streamed)>480:raise ValueError('Oversized memory reply')
                            row.setdefault('first_delta_ms',(time.monotonic()-start)*1000)
                            # Prepared audio remains private until exhaustion.
                            yield delta
                    result = ref.last_result
                else:
                    result = await ref.reply(task, boundary['evidence'], row['id'])
                current()
                text = result.get('text')
                if (result.get('status') != 'completed' or not isinstance(text, str)
                        or not text.strip() or len(text) > 480):
                    raise ValueError('Incomplete or oversized memory reply')
                if hasattr(ref, 'stream_text') and streamed!=text:
                    raise ValueError('Streamed memory text changed at completion')
                row.update(result=result, completed=True,
                           text_ready_ms=(time.monotonic()-start)*1000)
        except BaseException as error:
            row['error_type'] = type(error).__name__
            raise
        finally:
            # Join both branches before retiring their transport; neither a
            # failed lookup nor cancellation may leave a connect task alive.
            for pending in work:
                if not pending.done():pending.cancel()
            if any(not p.done() for p in work):await asyncio.gather(*work, return_exceptions=True)
            if ref is not None:
                # Response completion is already verified. Transport teardown
                # must not delay speaking; it remains owned and bounded.
                cleanup = asyncio.create_task(self._retire(ref, row))
                self.cleanup.add(cleanup)
                cleanup.add_done_callback(self.cleanup.discard)
        current()
        if not hasattr(ref, 'stream_text'):
            yield text
        # Normal exhaustion is the terminal publication barrier.
        return

    async def _retire(self, ref, row):
        start = time.monotonic()
        try:
            async with asyncio.timeout(4):
                await ref.close()
        except Exception as error:
            row['close_error_type'] = type(error).__name__
            # Real reference uses websockets' bounded close and transport.
            ws = getattr(ref, 'ws', None)
            transport = getattr(ws, 'transport', None)
            if transport is not None: transport.abort()
        finally:
            row['close_ms'] = (time.monotonic()-start)*1000
            self.active.discard(ref)

    async def close(self):
        self.closed = True
        if self.cleanup:
            await asyncio.gather(*tuple(self.cleanup), return_exceptions=True)


def make_conversation(store, *, scope, recall, speech, provider_store=None,
                      reference_factory=NativeTextReference,
                      evidence_qualifier=qualify_context):
    """Owner-qualified short-sentence preset, only for the opt-in memory path."""
    from tavi.chunked_conversation import ChunkedConversation
    provider = MemoryTextProvider(provider_store if provider_store is not None else store,
        scope=scope, recall=recall, reference_factory=reference_factory,
        evidence_qualifier=evidence_qualifier)
    return ChunkedConversation(store, provider=provider, speech=speech,
                               context_revision=scope, sentence_minimum=1)
