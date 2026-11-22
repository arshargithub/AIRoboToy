"""Bounded synthetic text-only prompt comparison with local K trace replay."""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

from .benchmark_reply_overlap import overlap
from .conversation_providers import PaidText, INSTRUCTIONS, MODEL, REQUEST_RESERVATION
from .local_speech import LocalSpeech
from .qualify_reply_overlap import Replay
from .storage import Store

CONCISE_INSTRUCTIONS=INSTRUCTIONS.replace(
    'Reply in one to three short spoken sentences, normally under 45 words. ',
    'Give one complete answer in one or two short spoken sentences, normally 15 to 30 words. '
).replace('For a story, tell a short vivid story rather than an introduction.',
          'For a story, tell a complete two-sentence micro-adventure with an ending, rather than an introduction.')
CASES=(('craft','Paprika, what can we build with three cushions and a blanket?'),
       ('story','Tell me a short story about a fox building a boat.'),
       ('explanation','Why does the moon look different on different nights?'))


async def run():
    path=Path('experiments/asr-mlx/concise-reply-protocol.json')
    plan=json.loads(path.read_text());assert plan['model']==MODEL
    folder=Path('.tavi/concise-replies')/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder.mkdir(parents=True)
    store=Store('.tavi/simulation/simulation.sqlite3')
    provider=PaidText(store);original=provider.responses
    initial=store.used_micro_usd();ceiling=initial+12*REQUEST_RESERVATION
    class Responses:
        def __init__(self,instructions):self.instructions=instructions
        async def create(self,**kwargs):
            kwargs['instructions']=self.instructions
            assert len(json.dumps(kwargs).encode())<16384
            return await original.create(**kwargs)
    report={'protocol':plan,'protocol_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'initial_spent_reserved_usd':initial/1e6,'maximum_additional_reservation_usd':.6,
        'instruction_hashes':{key:hashlib.sha256(text.encode()).hexdigest() for key,text in
            [('baseline',INSTRUCTIONS),('concise',CONCISE_INSTRUCTIONS)]},
        'rows':[],'completed':False}
    voice=LocalSpeech('kokoro-k-mlx')
    def save():
        report['final_spent_reserved_usd']=store.used_micro_usd()/1e6
        (folder/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    try:
        for repeat in range(2):
            for key,prompt in CASES[repeat:]+CASES[:repeat]:
                for variant in (('baseline','concise') if repeat==0 else ('concise','baseline')):
                    if store.used_micro_usd()+REQUEST_RESERVATION>ceiling:raise ValueError('Pilot budget exhausted')
                    provider.responses=Responses(INSTRUCTIONS if variant=='baseline' else CONCISE_INSTRUCTIONS)
                    row={'case':key,'repeat':repeat+1,'variant':variant,'text':'','deltas':[]}
                    began=time.perf_counter()
                    async for delta in provider.stream_reply([{'role':'user','content':prompt}]):
                        row['text']+=delta;row['deltas'].append({'at_ms':(time.perf_counter()-began)*1000,'characters':len(delta)})
                    row['text_completed_ms']=(time.perf_counter()-began)*1000
                    row['words']=len(row['text'].split());report['rows'].append(row);save()
                    print(key,repeat+1,variant,'text',round(row['text_completed_ms']),'ms','words',row['words'],flush=True)
        await voice.prepare()
        for row in report['rows']:
            trace,_=await overlap(Replay(row),voice,[])
            row['K_replay']={k:trace[k] for k in ('chunks','predicted_gap_ms','text_completed_ms','duration_ms')}
            row['first_guarded_WAV_ms']=max(trace['text_completed_ms'],trace['first_speculative_audio_ms'])
            save()
        report['completed']=True;save()
    finally:
        save();await voice.close();await provider.close();store.close()
    print(json.dumps({'report':str(folder/'report.json'),'completed':report['completed'],
                      'additional_spent_reserved_usd':report['final_spent_reserved_usd']-initial/1e6}),flush=True)


if __name__=='__main__':asyncio.run(run())
