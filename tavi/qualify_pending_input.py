"""Replay saved goodbye race into the real controller/K without paid inference.

ASR text and event intervals are frozen from the saved run and its local replay;
this does not remeasure native ASR or audible response latency.
"""
import asyncio
import hashlib
import json
from pathlib import Path
import time

from .benchmark_mlx_asr import used_budget
from .chunked_conversation import ChunkedConversation
from .local_speech import LocalSpeech, validate_wave
from .storage import Store


async def run():
    source=Path('.tavi/private-conversation-results/conversation-faa3159cff7f187773029dd0f13333319cbac092225e8c8d923ba378c3ca407a.json')
    replay=Path('.tavi/private-conversation-audio/conversation-faa3159cff7f1877/turbo-window-replay.json')
    original=json.loads(source.read_text());decoded=json.loads(replay.read_text())
    words={r['utterance']:r['text'] for r in decoded['rows']}
    events=[m for m in original['server']['metrics'] if m.get('utterance') in (8,9)
            and m['kind'] in ('speech_started','speech_ended','recognition_final')]
    class Forbidden:
        calls=0
        async def stream_reply(self,history):
            self.calls+=1
            raise AssertionError('Goodbye/tail must not request paid reasoning')
            yield ''
        async def close(self):pass
    provider=Forbidden();store=Store();voice=LocalSpeech('kokoro-k-mlx')
    c=ChunkedConversation(store,provider=provider,speech=voice)
    report={'scope':__doc__,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'decoder_replay_sha256':hashlib.sha256(replay.read_bytes()).hexdigest(),
            'initial_budget_usd':used_budget(),'completed':False}
    try:
        await voice.prepare();c.start('replayed')
        # Establish a confirmed session using a local name-only greeting, not a
        # paid turn. Simulate playback acknowledgements, never use speakers.
        c.feed('replayed',{'events':[{'type':'speech_started','utterance':1},
             {'type':'recognition','utterance':1,'text':'Paprika.','final':True}]})
        async with asyncio.timeout(15):
            while not c.audio:await asyncio.sleep(.01)
        greeting=c.audio
        for command in ('started','played'):
            assert c.command('replayed',command,{'response_id':greeting['id'],'sequence':0})
        start=time.monotonic();origin=events[0]['at']
        for event in events:
            await asyncio.sleep(max(0,start+event['at']-origin-time.monotonic()))
            n=event['utterance']
            e={'type':'recognition' if event['kind']=='recognition_final' else event['kind'],'utterance':n}
            if e['type']=='recognition':e.update(text=words[n],final=True,recognition_id=event['recognition_id'])
            c.feed('replayed',{'events':[e]})
            c.last_frame=time.monotonic()  # The real stream supplied quiet PCM throughout.
        async with asyncio.timeout(15):
            while not c.audio:await asyncio.sleep(.01)
        audio=c.audio
        validate_wave(audio['wav'],24000)
        assert c.close_after_playback and not c.snapshot()['pending_input']
        assert c.accepted_utterance==8 and provider.calls==0
        for command in ('started','played'):
            assert c.command('replayed',command,{'response_id':audio['id'],'sequence':0})
        assert not c.engaged
        c.feed('replayed',{'events':[{'type':'speech_started','utterance':10},
               {'type':'recognition','utterance':10,'text':words[10],'final':True}]})
        await asyncio.sleep(0)
        assert not c.engaged and provider.calls==0
        report.update(completed=True,goodbye_accepted=True,queued_tail_ignored=True,
             goodbye_valid_WAV=True,session_closed_after_ACK=True,post_close_comment_ignored=True,
             provider_calls=provider.calls,metrics=list(c.metrics),final_budget_usd=used_budget())
        assert report['final_budget_usd']==report['initial_budget_usd']
    finally:
        await c.close();store.close()
        replay.with_name('pending-input-controller-fix.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('scope','metrics')},indent=2),flush=True)


if __name__=='__main__':asyncio.run(run())
