"""One frozen E5 engine/repetition; cross-run acceptance is a separate review.

The caller supplies a frozen protocol, never an engine selected from a running
trial. Repeated runs use fresh databases. Provider work is metered by the same
loopback gateway. No automated model judge scores quality. No family data or audio is read.
"""
import argparse
import json
import os
import signal
import time
from experiments.memory.runtime import SSD,ROOT,MODEL,require_ssd
from experiments.memory.pilot import Process,answer
from experiments.memory.context_envelope import pack
from experiments.memory.build_e5_corpus import validate
from tavi.experiment_workflow import begin,audit


def run(protocol):
    require_ssd();os.environ['TIKTOKEN_CACHE_DIR']=str(SSD/'models/tiktoken')
    import tiktoken,httpx
    encoding=tiktoken.get_encoding('o200k_base')
    folder,plan=begin(protocol,run_root=SSD/'runs/scored');print(json.dumps({'run':str(folder),'audit':audit(folder)}),flush=True)
    corpus=json.loads((ROOT/plan['configuration']['corpus']).read_text());validate(corpus)
    engine=plan['configuration']['engine'];broker=json.loads((SSD/'private-config/broker.json').read_text())
    directory=SSD/'databases'/folder.parent.name/(folder.name+'-'+engine);logs=folder/'logs';logs.mkdir()
    observations={'ingests':[],'queries':[],'native_profiles':[],'operations':[],'errors':[]};worker=None;active=[]
    def save():(folder/'observations.json').write_text(json.dumps(observations,indent=2))
    def send(request,timeout=420):
        result=worker.send(request,timeout=timeout)
        if not result['ok']:raise RuntimeError(result['error'])
        return result['result']
    def start():
        nonlocal worker
        worker=Process(engine,directory,logs,'qualification_worker.py')
        send({'op':'initialize'})
    def query(question):
        began=time.monotonic();retrieval=send({'op':'query','question':question,'people':corpus['people']})
        envelope=pack(engine,retrieval['native_context'],active,question['audience_ids'],encoding)
        return {'retrieval':retrieval,'envelope':envelope,'context_ready_ms':(time.monotonic()-began)*1000}
    def expired(*args):raise TimeoutError('Frozen E5 run wall bound reached')
    signal.signal(signal.SIGALRM,expired);signal.alarm(plan['limits']['maximum_wall_seconds'])
    try:
        start()
        for index,episode in enumerate(corpus['episodes']):
            began=time.monotonic();result=send({'op':'ingest','episode':episode,'people':corpus['people']})
            active.append(episode)
            # This is a retrieval/support readiness probe, not a correctness
            # label: semantic evidence is assessed separately against held-out Qs.
            probe=query({'id':'availability-'+episode['id'],'text':episode['text'],'asker':episode['speaker_id'] if episode['speaker_id'] in corpus['people'] else 'p1',
                         'audience_ids':episode['audience_ids'],'at':episode['at']})
            headers=json.loads(probe['envelope']['context'])['source_headers']
            observations['ingests'].append({'source_id':episode['id'],'result':result,
                'queryable_after_ms':(time.monotonic()-began)*1000,'source_found':episode['id'] in headers,'probe':probe})
            if index==29:
                observations['operations'].append({'kind':'duplicate','result':send({'op':'ingest','episode':episode,'people':corpus['people']})})
            for question in corpus['questions']:
                if question['after']!=episode['id']:continue
                # One declared cold-process read per ten questions, not a cold
                # embedding/API/model machine restart. Label this accurately.
                cold=len(observations['queries'])%10==0
                if cold:worker.stop();start()
                record={'question':question,'cold_adapter_process':cold,**query(question)}
                public_question={k:question[k] for k in ('id','text','asker','audience_ids','at')}
                record['answer']=answer(engine,public_question,corpus['people'],record['envelope']['context'],broker)
                observations['queries'].append(record);save()
                record['review_status']='pending_blinded_source_review';save()
                if question['category']=='pattern':
                    before=time.monotonic()
                    native=send({'op':'profiles','question':question,'people':corpus['people']})
                    observations['native_profiles'].append({'question_id':question['id'],'native':native,
                        'available_after_query_ms':(time.monotonic()-before)*1000});save()
            save();print(json.dumps({'engine':engine,'episode':episode['id'],'answers':len(observations['queries'])}),flush=True)
        # A full-source deletion and duplicate-stale retry are checked using
        # the same projection rebuild boundary, not native deletion promises.
        sid='e120';deleted=send({'op':'delete','source_id':sid,'people':corpus['people']},timeout=1200)
        active=[e for e in active if e['id']!=sid]
        stale=send({'op':'ingest','episode':corpus['episodes'][-1],'people':corpus['people']})
        worker.stop();start()
        q=next(q for q in corpus['questions'] if q['after']==sid)
        record=query(q)
        observations['operations'].append({'kind':'delete_restart_stale_retry','source_id':sid,'delete':deleted,'stale_retry':stale,'query':record})
        save()
    except Exception as exc:
        observations['errors'].append(type(exc).__name__+': '+str(exc));save()
    finally:
        signal.alarm(0)
        if worker:worker.stop()
        r=httpx.post(broker['base_url']+'/control/disable-paid',headers={'Authorization':'Bearer '+broker['token']},timeout=100);r.raise_for_status()
        (folder/'calls-final.json').write_text(json.dumps(r.json()['calls'],indent=2));save()
    print(json.dumps({'run':str(folder),'errors':observations['errors'],'awaiting':'critical review, native-profile labels and finish'}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('protocol');run(p.parse_args().protocol)
