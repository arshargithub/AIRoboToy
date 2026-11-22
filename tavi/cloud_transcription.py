"""Bounded OpenAI transcription for synthetic or explicitly consented NEW adult tests.

No filesystem/audio capture is performed here. Existing local-only recordings
must never be routed into this adapter. It is not selected by live conversation.
"""
import asyncio
from io import BytesIO
import math
from uuid import uuid4
import wave
import time

from .conversation_providers import runtime_key
from .storage import APPROVED_BUDGET_MICRO_USD

TRANSCRIPTION_MODEL='gpt-transcribe'
RESERVATION=50_000
MICRO_USD_PER_SECOND=75  # Official $0.0045/minute, checked3 November2026.


def validate_input(data,source_kind):
    if source_kind not in ('synthetic','new_adult_test'):
        raise ValueError('Only synthetic or explicitly consented new adult test audio is authorized')
    if not isinstance(data,bytes) or not 44<len(data)<=800000:raise ValueError('Invalid bounded WAV')
    with wave.open(BytesIO(data)) as wav:
        if wav.getnchannels()!=1 or wav.getsampwidth()!=2 or wav.getframerate() not in (16000,24000) or wav.getcomptype()!='NONE':
            raise ValueError('Expected mono PCM16 WAV at16/24kHz')
        n=wav.getnframes();seconds=n/wav.getframerate()
        if not 0<seconds<=12 or len(wav.readframes(n))!=n*2:raise ValueError('Audio must be complete and at most12 seconds')
    return seconds


class CloudTranscription:
    def __init__(self,store,client=None):
        self.store=store
        if client is None:
            from openai import AsyncOpenAI
            client=AsyncOpenAI(api_key=runtime_key(),base_url='https://api.openai.com/v1',max_retries=0,timeout=18)
        self.client=client
        self.transcriptions=client.audio.transcriptions

    async def transcribe(self,data,*,source_kind,consent=False):
        if consent is not True:raise ValueError('Explicit test-specific cloud consent is required')
        duration=validate_input(data,source_kind)
        request_id='transcription:'+uuid4().hex
        self.store.reserve(request_id,RESERVATION,APPROVED_BUDGET_MICRO_USD)
        began=time.monotonic()
        # Failed/ambiguous/cancelled calls retain their reservation. No retries
        # or substitute model are introduced by this adapter.
        async with asyncio.timeout(20):
            response=await self.transcriptions.create(model=TRANSCRIPTION_MODEL,
                file=('new-test.wav',data,'audio/wav'),languages=['en'],response_format='json')
        text=response.text
        if not isinstance(text,str) or len(text)>2000:raise ValueError('Invalid bounded transcription')
        usage=response.usage
        settled=False
        if usage is not None and getattr(usage,'type',None)=='duration':
            seconds=usage.seconds
            if not isinstance(seconds,(int,float)) or not math.isfinite(seconds) or not 0<=seconds<=13:
                raise ValueError('Invalid billed duration; reservation retained')
            # Round up a second and never account for less than input duration.
            charge=math.ceil(max(duration,seconds))*MICRO_USD_PER_SECOND
            self.store.settle(request_id,charge);settled=True
        return {'text':text,'elapsed_ms':(time.monotonic()-began)*1000,
                'input_duration_seconds':duration,'model':TRANSCRIPTION_MODEL,
                'usage':usage.model_dump() if usage is not None and hasattr(usage,'model_dump') else None,
                'reservation_settled':settled,'scores_available':False,
                'model_identity_note':'Provider currently documents this alias without an immutable dated snapshot; exact model version cannot be claimed.'}

    async def close(self):await self.client.close()
