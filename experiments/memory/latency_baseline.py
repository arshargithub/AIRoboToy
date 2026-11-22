"""Frozen serial/whole-text reference from MEMORY-COMBINED-01.
Reference source SHA256:a95886dcaac02608a73e0e18dd587c8b4bd7f5922609cb500a3cceda2f0f5e31
Only class names/import wiring changed; same model/mission/terminal guard.
"""
"""Native model text-only reference with completed-text K publication barrier.

No model-produced evidence receipt. Canonical input qualification and semantic
evaluation remain separate; this is not equivalent to the receipt/K contract.
"""
import asyncio
import time
from uuid import uuid4
from experiments.memory.native_voice import response_options
from experiments.memory.decision_contract_v2 import snapshot
from tavi.realtime_reference import RealtimeReference,RESERVATION,charge_usage
from tavi.storage import APPROVED_BUDGET_MICRO_USD
from tavi.sentence_chunks import SentenceChunks


class BaselineNativeTextReference(RealtimeReference):
    async def reply(self,task,evidence,case_id):
        options=response_options(task,evidence,case_id);options['output_modalities']=['text']
        reservation='memory-native-text:'+uuid4().hex
        self.store.reserve(reservation,RESERVATION,APPROVED_BUDGET_MICRO_USD)
        result={'case_id':case_id,'request':options,'reservation':reservation,'text':'','usage_settled':False}
        response_id=None;start=time.monotonic()
        await self.send('response.create',response=options)
        async with asyncio.timeout(35):
            while True:
                event=await self.receive();kind=event['type']
                if kind=='response.created':
                    if response_id:raise ValueError('Unexpected additional response')
                    response=event['response'];response_id=response['id']
                    if response.get('metadata',{}).get('case_id')!=case_id:raise ValueError('Unbound native case')
                elif kind in ('response.output_text.delta','response.output_audio.delta','response.done'):
                    actual=event['response']['id'] if kind=='response.done' else event.get('response_id')
                    if not response_id or actual!=response_id:raise ValueError('Unbound native output')
                    if kind=='response.output_audio.delta':raise ValueError('Unexpected native audio in text-only reference')
                    if kind=='response.output_text.delta':
                        result['text']+=event['delta']
                        if len(result['text'])>5000:raise ValueError('Text exceeds collection bound')
                    else:
                        response=event['response'];result['terminal_ms']=(time.monotonic()-start)*1000
                        result['status']=response['status'];result['usage']=response.get('usage')
                        charge=charge_usage(result['usage'])
                        if charge is not None:self.store.settle(reservation,charge);result['usage_settled']=True
                        if result['status']!='completed' or not result['text'].strip():raise ValueError('Incomplete native text')
                        terminal=''.join(c.get('text','') for item in response.get('output',[]) for c in item.get('content',[]) if c.get('type')=='output_text')
                        if terminal!=result['text']:raise ValueError('Terminal text does not match collected text')
                        if any(c.get('type')=='refusal' for item in response.get('output',[]) for c in item.get('content',[])):
                            raise ValueError('Refused native response')
                        return result

"""Opt-in memory provider for the existing sentence conversation controller.

Trusted scope and recall are injected by the local host. No voice identity is
inferred here. Live robot defaults do not select this experimental adapter.
"""
import asyncio
from collections import deque
from copy import deepcopy
import time
from uuid import uuid4


from experiments.memory.reply_boundary import qualify_context


class BaselineMemoryTextProvider:
    def __init__(self, store, *, scope, recall, reference_factory=BaselineNativeTextReference):
        self.store, self.scope, self.recall = store, scope, recall
        self.reference_factory = reference_factory
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
        qualify_context(task, {'facts': []}, [])

        def current():
            if self.closed or self.scope() != issued:
                raise ValueError('Memory scope changed')

        ref = None
        row = {'id': uuid4().hex, 'task': task, 'completed': False}
        self.observations.append(row)
        start = time.monotonic()
        try:
            async with asyncio.timeout(55):
                raw = await self.recall(deepcopy(task))
                current()
                boundary = qualify_context(task, raw['evidence'], raw['sources'])
                row['boundary'] = boundary
                row['context_ms'] = (time.monotonic()-start)*1000
                # Bounded independent transports; never reuse a cancelled one.
                if len(self.cleanup) >= 2:
                    await asyncio.wait(self.cleanup, return_when=asyncio.FIRST_COMPLETED)
                current()
                ref = self.reference_factory(self.store)
                self.active.add(ref)
                t = time.monotonic()
                await ref.connect()
                current()
                row['connection_ms'] = (time.monotonic()-t)*1000
                result = await ref.reply(task, boundary['evidence'], row['id'])
                current()
                text = result.get('text')
                if (result.get('status') != 'completed' or not isinstance(text, str)
                        or not text.strip() or len(text) > 480):
                    raise ValueError('Incomplete or oversized memory reply')
                row.update(result=result, completed=True,
                           text_ready_ms=(time.monotonic()-start)*1000)
        except BaseException as error:
            row['error_type'] = type(error).__name__
            raise
        finally:
            if ref is not None:
                # Response completion is already verified. Transport teardown
                # must not delay speaking; it remains owned and bounded.
                cleanup = asyncio.create_task(self._retire(ref, row))
                self.cleanup.add(cleanup)
                cleanup.add_done_callback(self.cleanup.discard)
        current()
        # Only one complete validated text is yielded; K never sees deltas.
        yield text

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


def make_baseline(store, *, scope, recall, speech, provider_store=None,
                      reference_factory=BaselineNativeTextReference):
    """Owner-qualified short-sentence preset, only for the opt-in memory path."""
    from tavi.chunked_conversation import ChunkedConversation
    provider = BaselineMemoryTextProvider(provider_store if provider_store is not None else store,
        scope=scope, recall=recall, reference_factory=reference_factory)
    return ChunkedConversation(store, provider=provider, speech=speech,
                               context_revision=scope, sentence_minimum=1)
