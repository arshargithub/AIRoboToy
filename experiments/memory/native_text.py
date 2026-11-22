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


class NativeTextReference(RealtimeReference):
    async def reply(self,task,evidence,case_id):
        # Historical whole-text callers retain the same contract.
        async for _ in self.stream_text(task,evidence,case_id):pass
        return self.last_result

    async def stream_text(self,task,evidence,case_id):
        """Private deltas; caller MUST gate playback on normal exhaustion."""
        self.last_result = None
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
                        result.setdefault('first_delta_ms',(time.monotonic()-start)*1000)
                        result.setdefault('text_events',[]).append({'at_ms':(time.monotonic()-start)*1000,'text':event['delta']})
                        yield event['delta']
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
                        self.last_result = result
                        return


async def speak_completed(voice,result,task,evidence,*,issued_snapshot,current_snapshot):
    if result.get('status')!='completed':raise ValueError('Reply is not complete')
    if current_snapshot!=issued_snapshot or snapshot(task,evidence)!=issued_snapshot:
        raise ValueError('Stale reply context')
    text=result['text']
    if not isinstance(text,str) or not text.strip() or len(text)>480:raise ValueError('Reply exceeds local voice bound')
    splitter=SentenceChunks();parts=splitter.feed(text)+splitter.finish()
    if ''.join(parts)!=text:raise ValueError('Incomplete text partition')
    duration=0
    try:
        for index,part in enumerate(parts):
            started=time.monotonic();audio=await voice.synthesize(part);duration+=audio.duration_ms
            if duration>30000:raise ValueError('Reply exceeds voice duration bound')
            yield {'index':index,'text':part,'audio':audio,'synthesis_ms':(time.monotonic()-started)*1000}
    except BaseException:
        await voice.close();raise
