"""One bounded paced synthetic integration screen with a silent virtual sink.

No microphone, speaker, old human recording or automatic replay/retry path.
This checks transport/context/state boundaries, not acoustic/human acceptance.
"""
import asyncio
import audioop
import base64
import hashlib
import json
import time
import wave
from uuid import uuid4

from .engaged_native import EngagedNativeSession
from .experiment_workflow import ROOT, begin, finish, audit
from .storage import Store


class Envelope:
    def __init__(self, store):
        self.store=store;self.initial=store.used_micro_usd();self.calls=0
    def used_micro_usd(self):return self.store.used_micro_usd()
    def reserve(self, key, amount, cap):
        if self.calls>=5 or self.used_micro_usd()+amount>self.initial+5_000_000:
            raise ValueError('Synthetic request/spend ceiling exceeded')
        self.store.reserve(key,amount,cap);self.calls+=1
    def settle(self, key, amount):self.store.settle(key,amount)


async def run():
    folder,plan=begin('experiments/realtime/engagement-synthetic-v3.json')
    store=Store(ROOT/'.tavi/simulation/simulation.sqlite3');envelope=Envelope(store)
    session=EngagedNativeSession(envelope,uuid4().hex)
    report={'source_kind':'synthetic_K_only','physical_playback':False,'events':[],
            'input_integrity':[],'observations':[],'completed':False}
    all_pcm=bytearray();events=[];error=None
    manifest=json.loads((ROOT/'.tavi/engagement-synth-v1/manifest.json').read_text())
    if manifest['origin']!='synthetic_K_only':raise ValueError('Synthetic source required')
    def persist():
        report['rows']=session.rows;report['trace']=session.trace
        report['local_checks']=session.local_checks
        report['spent_reserved_usd']=store.used_micro_usd()/1e6
        (folder/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    async def tick(pcm=bytes(1024)):
        before=time.monotonic()
        all_pcm.extend(pcm)
        result=await session.frame({'sequence':session.sequence+1,'pcm':base64.b64encode(pcm).decode()})
        events.extend(result['events'])
        report['events'].extend({k:v for k,v in e.items() if k!='pcm'} for e in result['events'])
        if session.error:raise ValueError(session.error)
        await asyncio.sleep(max(0,.032-(time.monotonic()-before)))
    async def until(predicate, seconds=25):
        deadline=time.monotonic()+seconds
        while not predicate():
            if time.monotonic()>deadline:raise ValueError('Synthetic integration stage timed out')
            await tick()
    async def feed(case):
        item=next(c for c in manifest['cases'] if c['id']==case)
        path=ROOT/item['wav']
        if path.is_symlink() or path.resolve().parent!=(ROOT/'.tavi/engagement-synth-v1').resolve():
            raise ValueError('Synthetic input escaped its frozen folder')
        with wave.open(str(path)) as w:
            if (w.getframerate(),w.getnchannels(),w.getsampwidth())!=(16000,1,2):raise ValueError('Wrong synthetic format')
            pcm=w.readframes(w.getnframes())
        pcm=bytes(16000)+pcm+bytes(32000)
        pcm+=bytes((-len(pcm))%1024)
        for offset in range(0,len(pcm),1024):await tick(pcm[offset:offset+1024])
    async def complete():
        await until(lambda:session.current is not None and session.current.get('done'))
        row=session.current
        if row.get('status')!='completed' or row.get('blocked') or not row.get('frames'):
            raise ValueError('Synthetic reply not complete')
        # Virtual acknowledgement only; no speakers or browser playback.
        await session.played({'id':row['response_id']})
        if session.closure_job:await until(lambda:session.closure_job.done(),4)
        persist()
        return row
    try:
        # Internal fixture switches only, not assertions of human consent.
        await session.prepare({'adult':True,'cloud':True,'recording':True,'save_audio':False,
                               'context_fixture':True,'workflow':'engagement-v1'},record_workflow=False)
        session.choices={'source_kind':'synthetic_K_only','workflow':'engagement-v1','physical_playback':False}
        report['recognition_profile']=session.decoder.profile
        await feed('ambient');await until(lambda:session.local_job and session.local_job.done(),4)
        report['observations'].append({'stage':'initial_unaddressed','provider_connected':session.channel_open,
                                       'requests':envelope.calls,'spent_reserved_delta':store.used_micro_usd()-envelope.initial})
        if session.channel_open or envelope.calls:raise ValueError('Standby crossed provider boundary')
        await feed('fort');await complete()
        report['observations'].append({'stage':'first_context_reply','text':session.current['text']})
        await feed('story');await until(lambda:session.current is not None and len(session.rows)==2 and session.current.get('frames',0)>0)
        await session.interrupt({'id':session.current['response_id'],'played_ms':0})
        await until(lambda:session.current['done'] and session.current.get('truncated_ack'))
        report['observations'].append({'stage':'virtual_interruption','status':session.current['status'],
                                       'truncated_ack':session.current['truncated_ack'],'heard_ms':0})
        await feed('change');await complete()
        await feed('fox');await complete()
        report['observations'].append({'stage':'followup_context_reply','text':session.current['text']})
        await feed('close');await complete()
        await until(lambda:session.mode=='standby',5)
        before=envelope.calls
        await feed('ambient');await until(lambda:session.local_job and session.local_job.done(),4)
        report['observations'].append({'stage':'post_goodbye_unaddressed','provider_connected':session.channel_open,
                                       'additional_requests':envelope.calls-before})
        for row in session.rows:
            pcm=bytes(all_pcm[row['input_start_sample']*2:row['input_end_sample']*2])
            converted,_=audioop.ratecv(pcm,2,1,16000,24000,None)
            report['input_integrity'].append(hashlib.sha256(converted).hexdigest()==row['input_pcm24_sha256']
                                             and len(converted)==row['input_pcm24_bytes'])
        report['completed']=True
    except Exception as exc:
        error=type(exc).__name__
        report['error']={'type':error,'detail':str(exc)[:180] if isinstance(exc,ValueError) else None}
    finally:
        await session.stop();persist()
    rows=session.rows;observations=report['observations']
    metrics={'requests':envelope.calls,'errors':int(error is not None),
        'context_bound_replies':sum(r.get('speaker')=='unknown' and r.get('context_fact_ids')==['pretend-fort','pretend-mascot'] for r in rows),
        'complete_replies':sum(r.get('status')=='completed' and not r.get('blocked') for r in rows),
        'truncated_replies':sum(bool(r.get('blocked') and r.get('truncated_ack')) for r in rows),
        'input_integrity_checks':sum(report['input_integrity']),
        'local_only_checks':sum(r.get('purpose')=='address' and r.get('addressed') is False for r in session.local_checks),
        'goodbye_closed_sessions':session.closed_sessions,
        'semantic_fixture_slots':sum(('Star Nest'.casefold() in r.get('text','').casefold() if i==0 else 'pixel' in r.get('text','').casefold()) for i,r in enumerate(rows) if i in (0,3)),
        'additional_spent_reserved_usd':(store.used_micro_usd()-envelope.initial)/1e6}
    report['metrics']=metrics
    report['interpretation']='One synthetic integration screen, paced real Silero/MLX and cloud native speech; same K voice, fixed fictional context, virtual zero-heard interruption/played ACKs. No physical playback, acoustic p95, family identity, memory learning or human acceptance.'
    persist()
    record=finish(folder,metrics,artifacts=[folder/'results.json'],completed=report['completed'],error=error)
    store.close()
    print(json.dumps({'run':str(folder),'decision':record['decision'],'audit':audit(folder)},indent=2))


if __name__=='__main__':asyncio.run(run())
