"""Bounded prerequisite screen; not the full E5 held-out qualification."""
import argparse
import json
import os
from pathlib import Path
import signal
import time

from experiments.memory.runtime import SSD,ROOT,require_ssd
from experiments.memory.pilot import Process,ENVIRONMENTS,answer
from experiments.memory.context_envelope import pack
from tavi.experiment_workflow import begin,audit


def run(protocol):
    require_ssd();os.environ['TIKTOKEN_CACHE_DIR']=str(SSD/'models/tiktoken')
    import tiktoken,httpx
    encoding=tiktoken.get_encoding('o200k_base')
    folder,plan=begin(protocol,run_root=SSD/'runs/scored');print(json.dumps({'run':str(folder),'audit':audit(folder)}),flush=True)
    fixture=json.loads((ROOT/'experiments/memory/pilot-fixtures.json').read_text())
    by_id={e['id']:e for e in fixture['episodes']}
    episodes=[by_id[s] for s in plan['configuration']['episode_order']]
    broker=json.loads((SSD/'private-config/broker.json').read_text())
    logs=folder/'logs';logs.mkdir();workers={};events=[];queries=[];profiles=[];errors={}
    def save():
        (folder/'observations.json').write_text(json.dumps({'events':events,'queries':queries,'profiles':profiles,'errors':errors},indent=2))
    def start(engine):
        directory=SSD/'databases'/folder.parent.name/(folder.name+'-'+engine)
        w=Process(engine,directory,logs,'qualification_worker.py');workers[engine]=w
        result=w.send({'op':'initialize'});events.append({'engine':engine,'phase':'initialize',**result})
        if not result['ok']:raise RuntimeError(result['error'])
        return w
    def send(engine,phase,request,**kw):
        result=workers[engine].send(request,**kw);events.append({'engine':engine,'phase':phase,**result});save()
        if not result['ok']:raise RuntimeError(result['error'])
        return result['result']
    def probe(engine,phase,text):
        question={'id':phase,'text':text,'asker':'p1','audience_ids':['p1','p2','p3','p4'],'at':'2026-02-05T16:00:00Z'}
        began=time.monotonic();retrieval=send(engine,phase,{'op':'query','question':question,'people':fixture['people']})
        active=[e for e in episodes if phase!='after_delete' or e['id']!='e15']
        envelope=pack(engine,retrieval['native_context'],active,question['audience_ids'],encoding)
        query={'engine':engine,'phase':phase,'question':question,'retrieval':retrieval,
            'envelope':envelope,'context_ready_ms':(time.monotonic()-began)*1000}
        query['answer']=answer(engine,question,fixture['people'],envelope['context'],broker)
        queries.append(query);save()
    def expired(*args):raise TimeoutError('Prerequisite screen wall bound reached')
    signal.signal(signal.SIGALRM,expired);signal.alarm(plan['limits']['maximum_wall_seconds'])
    try:
        for engine in plan['configuration'].get('engines',ENVIRONMENTS):
            try:
                start(engine)
                for episode in episodes:
                    request={'op':'ingest','episode':episode,'people':fixture['people']}
                    if episode['id']=='e09':
                        send(engine,'native_commit_ack_lost',{**request,'crash':'after_native'},expect_crash=True)
                        workers[engine].stop();start(engine)
                        result=workers[engine].send({'op':'query','question':{'text':'What colour?','asker':'p1','audience_ids':['p1']},'people':fixture['people']})
                        events.append({'engine':engine,'phase':'ambiguous_read','blocked':not result['ok'],**result});save()
                        send(engine,'recovery',{'op':'recover','people':fixture['people']})
                    else:send(engine,'ingest_'+episode['id'],request)
                    print(json.dumps({'engine':engine,'source':episode['id']}),flush=True)
                send(engine,'deduplicate',{'op':'ingest','episode':by_id['e13'],'people':fixture['people']})
                for phase,text in [('pattern','What kind of books might Sage enjoy?'),('correction','What colour does Sage prefer now?'),('identity','Which family member likes model boats?')]:
                    probe(engine,phase,text)
                q={'text':'Summarize preferences and cautiously supported repeated interests for each person.','audience_ids':['p1','p2','p3','p4'],'at':'2026-02-05T16:00:00Z'}
                native=send(engine,'native_profiles',{'op':'profiles','question':q,'people':fixture['people']})
                profiles.append({'engine':engine,**native});save()
                send(engine,'delete_intent_crash',{'op':'delete','source_id':'e15','people':fixture['people'],'crash':'after_tombstone'},expect_crash=True)
                workers[engine].stop();start(engine)
                blocked=workers[engine].send({'op':'query','question':{'text':'What award?','asker':'p1','audience_ids':['p1']},'people':fixture['people']})
                events.append({'engine':engine,'phase':'deleted_read','blocked':not blocked['ok'],**blocked});save()
                send(engine,'delete_recovery',{'op':'recover','people':fixture['people']})
                probe(engine,'after_delete','What award did Finley win at the football match?')
                # Replaying an old source must not resurrect its tombstone.
                send(engine,'stale_replay',{'op':'ingest','episode':by_id['e15'],'people':fixture['people']})
                workers[engine].stop();start(engine)
                probe(engine,'after_delete','What award did Finley win at the football match?')
            except Exception as exc:
                errors[engine]=type(exc).__name__+': '+str(exc);save()
            finally:
                if engine in workers:workers[engine].stop()
    finally:
        signal.alarm(0)
        for w in workers.values():w.stop()
        r=httpx.post(broker['base_url']+'/control/disable-paid',headers={'Authorization':'Bearer '+broker['token']},timeout=100);r.raise_for_status()
        (folder/'calls-final.json').write_text(json.dumps(r.json()['calls'],indent=2));save()
    print(json.dumps({'run':str(folder),'errors':errors,'awaiting':'explicit engineering review and finish'}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('protocol');run(p.parse_args().protocol)
