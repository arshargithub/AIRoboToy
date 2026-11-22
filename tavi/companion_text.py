"""Text-only native reply path for unidentified people, with no memory access.

The anonymous participant is a transport role, never a family identity or a
memory permission. No retrieval, ingestion, profile or bank is opened here.
"""
import asyncio
from contextlib import aclosing
from datetime import datetime, timezone
from uuid import uuid4
from experiments.memory.native_text import NativeTextReference
from tavi.realtime_reference import MODEL


class CompanionText:
    model = MODEL
    memory_enabled = False

    def __init__(self, store, *, reference_factory=NativeTextReference):
        self.store, self.reference_factory = store, reference_factory
        self.active = set()
        self.cleanup = set()
        self.closed = False

    async def stream_reply(self, history):
        if self.closed or not history or history[-1]['role'] != 'user':
            raise ValueError('No current request')
        task = {'actual_speaker_id': 'anonymous',
                'people': {'anonymous': 'Current unidentified speaker; no known identity'},
                'audience_ids': ['anonymous'], 'conversation_at': datetime.now(timezone.utc).isoformat(),
                'question': history[-1]['content'], 'recent_conversation': history[-12:-1], 'catalogue': []}
        ref = self.reference_factory(self.store)
        self.active.add(ref)
        try:
            await ref.connect()
            text = ''
            async with aclosing(ref.stream_text(task, {'facts': []}, uuid4().hex)) as stream:
                async for delta in stream:
                    text += delta
                    if self.closed or len(text) > 480:
                        raise ValueError('Reply cancelled or too long')
                    yield delta
            result = ref.last_result
            if not result or result.get('status') != 'completed' or result.get('text') != text or not text.strip():
                raise ValueError('Reply did not complete')
        finally:
            # A validated answer need not wait for the websocket close handshake.
            cleanup = asyncio.create_task(self._retire(ref))
            self.cleanup.add(cleanup)
            cleanup.add_done_callback(self.cleanup.discard)

    async def _retire(self, ref):
        try:
            async with asyncio.timeout(4):
                await ref.close()
        except Exception:
            transport = getattr(getattr(ref, 'ws', None), 'transport', None)
            if transport is not None: transport.abort()
        finally:
            self.active.discard(ref)

    async def close(self):
        self.closed = True
        if self.cleanup:
            await asyncio.gather(*tuple(self.cleanup), return_exceptions=True)


def conversation(store, *, speech):
    from tavi.chunked_conversation import ChunkedConversation
    return ChunkedConversation(store, provider=CompanionText(store), speech=speech, sentence_minimum=1)
