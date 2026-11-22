"""Actual K/experimental controller check with replayed synthetic text traces.

Playback ACKs are simulated and accelerated. No speakers, browser microphone or
cloud requests. This checks ordered delivery and invalidation, not listening.
"""
import argparse
import asyncio
import json
from pathlib import Path
import time

from .chunked_conversation import ChunkedConversation
from .local_speech import LocalSpeech, validate_wave
from .qualify_reply_overlap import Replay
from .storage import Store


async def run(path):
    rows=json.loads(path.read_text())['pairs']
    voice=LocalSpeech('kokoro-k-mlx'); store=Store()
    class Provider:
        def __init__(self): self.calls=0
        async def stream_reply(self, history):
            row=rows[self.calls%len(rows)]; self.calls+=1
            async for delta in Replay(row).stream_reply(history): yield delta
        async def close(self): pass
    provider=Provider(); c=ChunkedConversation(store,provider=provider,speech=voice)
    report={'scope':__doc__,'api_spend_usd':0,'turns':[],'completed':False}
    def request(text, number):
        c.feed('synthetic',{'events':[{'type':'speech_started','utterance':number},
               {'type':'recognition','utterance':number,'text':text,'final':True,'first_detection':True}]})
    async def ready():
        async with asyncio.timeout(22):
            while c.audio is None:
                if c.failure: raise ValueError('Experimental reply failed')
                await asyncio.sleep(.01)
        return c.audio
    async def finish(start):
        rid=c.controller.token.response_id; sequences=[]; first=None
        async with asyncio.timeout(30):
            while c.completed_response_id!=rid:
                audio=await ready()
                if first is None: first=(time.perf_counter()-start)*1000
                seq=audio['sequence']; sequences.append(seq)
                validate_wave(c.audio_bytes('synthetic',rid,seq),24000)
                assert c.command('synthetic','started',{'response_id':rid,'sequence':seq})
                await asyncio.sleep(.03)  # Simulated, not real audible duration.
                assert c.command('synthetic','played',{'response_id':rid,'sequence':seq})
                assert not c.command('synthetic','played',{'response_id':rid,'sequence':seq})
                await asyncio.sleep(0)
        assert sequences==list(range(len(sequences)))
        return {'first_chunk_ready_ms':first,'chunks':len(sequences),'sequence_order_verified':True}
    try:
        await voice.prepare(); c.start('synthetic')
        for number in range(1,4):
            start=time.perf_counter(); request('Paprika, tell me something playful.',number)
            report['turns'].append(await finish(start))
        request('Paprika, tell me a story.',4); audio=await ready(); old_id=audio['id']
        assert c.command('synthetic','started',{'response_id':old_id,'sequence':0})
        await asyncio.sleep(.12)
        c.feed('synthetic',{'events':[{'type':'speech_started','utterance':5}]})
        start=time.perf_counter()
        assert c.command('synthetic','interrupt',{'response_id':old_id,'utterance':5})
        assert c.audio is None and not c.chunks
        c.feed('synthetic',{'events':[{'type':'recognition','utterance':5,'text':'Make it a jungle adventure instead.',
                                     'final':True,'first_detection':False}]})
        report['replacement']=await finish(start)
        assert not c.command('synthetic','played',{'response_id':old_id,'sequence':0})
        try: c.audio_bytes('synthetic',old_id,1)
        except ValueError: pass
        else: raise AssertionError('Cancelled audio remained accessible')
        request('Goodbye, Paprika.',6); await finish(time.perf_counter())
        assert not c.engaged
        report.update(completed=True,interruption_invalidated_all_chunks=True,
                      replacement_recovered=True,goodbye_closed=True,cloud_calls=0,
                      rejected_stale_ack=True)
        print(json.dumps({k:v for k,v in report.items() if k!='scope'},indent=2))
    finally:
        path.with_name('controller-qualification.json').write_text(json.dumps(report,indent=2)+'\n')
        await c.close(); store.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('benchmark',type=Path)
    asyncio.run(run(p.parse_args().benchmark))
