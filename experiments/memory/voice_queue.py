"""Experimental sentence audio after the COMPLETE validated response.

No live controller uses this adapter. Transport, listening and interruption
qualification are required before promotion. The caller must close the async
generator on interruption so unfinished native synthesis is killed.
"""
import time
from tavi.sentence_chunks import SentenceChunks
from experiments.memory.decision_contract_v2 import validate


async def chunks(voice, value, task, evidence, *, issued_snapshot, current_snapshot):
    result = validate(value, task, evidence, issued_snapshot=issued_snapshot,
                      current_snapshot=current_snapshot)
    text = result['text']
    if len(text) > 480:
        raise ValueError('Complete reply exceeds voice bound')
    splitter = SentenceChunks()
    parts = splitter.feed(text) + splitter.finish()
    if ''.join(parts) != text:
        raise ValueError('Incomplete sentence partition')
    total = 0
    try:
        for index, part in enumerate(parts):
            start = time.monotonic()
            audio = await voice.synthesize(part)
            total += audio.duration_ms
            if total > 30000:
                raise ValueError('Combined reply exceeds voice duration bound')
            yield {'index': index, 'text': part, 'audio': audio,
                   'synthesis_ms': (time.monotonic()-start)*1000}
    except BaseException:
        await voice.close()
        raise
