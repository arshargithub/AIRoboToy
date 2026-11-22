"""Synthetic silent-sink integration fixture. No microphone or human evidence."""
import asyncio
import base64
import json
import time
import wave

from .experiment_workflow import begin, finish, audit, ROOT
from .realtime_lab import NativeSession
from .storage import Store


async def run():
    folder, plan=begin('experiments/realtime/relay-synthetic-protocol-v1.json')
    store=Store(ROOT/'.tavi/simulation/simulation.sqlite3');initial=store.used_micro_usd()
    session=NativeSession(store,'0'*32,maximum_requests=2)
    report={'source_kind':'synthetic_K_only','physical_playback':False,'rows':[],'completed':False}
    error=None
    def save():
        report['spent_reserved_usd']=store.used_micro_usd()/1e6
        (folder/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    try:
        # Internal fixture configuration; these booleans do NOT assert that a
        # real adult has consented or supplied any of the synthetic input.
        await session.prepare({'adult':True,'recording':True,'cloud':True,'save_audio':False},record_workflow=False)
        for case,interrupt in [('bridge',False),('close',True)]:
            with wave.open(str(ROOT/'.tavi/synthetic-asr-v1'/f'{case}.wav')) as wav:
                if (wav.getframerate(),wav.getnchannels(),wav.getsampwidth())!=(16000,1,2):raise ValueError('Wrong fixture format')
                pcm=wav.readframes(wav.getnframes())
            pcm=b'\0'*16000+pcm+b'\0'*32000
            pcm+=b'\0'*((-len(pcm))%1024)
            started=time.monotonic();row_index=len(session.rows);interrupted=False;seen=0
            for offset in range(0,len(pcm),1024):
                if store.used_micro_usd()-initial>int(plan['limits']['maximum_additional_api_usd']*1e6):raise ValueError('Fixture spend ceiling')
                result=await session.frame({'sequence':session.sequence+1,'pcm':base64.b64encode(pcm[offset:offset+1024]).decode()})
                seen+=sum(e['kind']=='audio' for e in result['events'])
                if interrupt and seen and not interrupted:
                    await session.interrupt({'id':session.current['response_id'],'played_ms':0});interrupted=True
                await asyncio.sleep(max(0,started+(offset+1024)/32000-time.monotonic()))
            deadline=time.monotonic()+20
            while len(session.rows)==row_index or not session.current['done'] or interrupt and not session.current.get('truncated_ack'):
                if session.error or time.monotonic()>deadline:raise ValueError(session.error or 'Fixture did not complete')
                result=await session.frame({'sequence':session.sequence+1,'pcm':base64.b64encode(b'\0'*1024).decode()})
                if interrupt and not interrupted and any(e['kind']=='audio' for e in result['events']):
                    await session.interrupt({'id':session.current['response_id'],'played_ms':0});interrupted=True
                await asyncio.sleep(.032)
            row=session.current
            if not interrupt:await session.played({'id':row['response_id'],'latency_ms':None})
            report['rows'].append({**row,'case':case,'synthetic_virtual_played_ack':not interrupt})
            save();print(case,row['status'],flush=True)
        report['completed']=True
    except Exception as exc:
        error=type(exc).__name__;report['error']={'type':error,'detail':str(exc)[:150] if isinstance(exc,ValueError) else None}
    finally:
        await session.stop();report['trace']=session.trace;save()
    metrics={'replies':len(report['rows']),'complete':sum(r.get('status')=='completed' for r in report['rows']),
             'cancelled_or_completed_and_truncated':sum(r.get('blocked') and r.get('truncated_ack') for r in report['rows']),
             'usage_settled':sum(r.get('usage_settled',False) for r in report['rows']),
             'errors':int(error is not None),'additional_spent_reserved_usd':(store.used_micro_usd()-initial)/1e6}
    report['metrics']=metrics
    report['interpretation']='Real local Silero, actual paced synthetic frames, official API, response relay and zero-heard-frame truncation. Virtual sink only; no human, browser sound or acoustic acceptance.'
    save();record=finish(folder,metrics,artifacts=[folder/'results.json'],completed=report['completed'],error=error)
    store.close();print(json.dumps({'run':str(folder),'decision':record['decision'],'audit':audit(folder)},indent=2))


if __name__=='__main__':asyncio.run(run())
