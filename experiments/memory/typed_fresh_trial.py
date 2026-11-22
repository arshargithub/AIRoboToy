"""Fresh fictional source-to-admission-to-store-to-render integration screen."""
from dataclasses import asdict
import json
import os
import signal
import time

from experiments.memory.runtime import ROOT, SSD, require_ssd
from experiments.memory.claim_admission_temporal import TemporalAdmissionPipeline
from experiments.memory.typed_store import TypedMemoryStore
from experiments.memory.typed_dialogue_strict import StrictTypedDialogue
from experiments.memory.typed_render import RenderedTypedDialogue
from tavi.experiment_workflow import begin, audit


def run():
    require_ssd()
    os.environ['TIKTOKEN_CACHE_DIR'] = str(SSD/'models/tiktoken')
    import httpx
    import tiktoken
    broker=json.loads((SSD/'private-config/broker.json').read_text())
    folder,plan=begin(ROOT/'experiments/memory/typed-fresh-protocol-v1.json',run_root=SSD/'runs/scored')
    print(json.dumps({'run':str(folder),'audit':audit(folder)}),flush=True)
    config=plan['configuration']
    fixture=json.loads((ROOT/config['input']).read_text())
    cases=json.loads((ROOT/config['cases']).read_text())
    observations={'sources':[],'cases':[],'errors':[],'trace':[]}
    store=TypedMemoryStore(folder/'source.sqlite3')
    def save():
        (folder/'observations.json').write_text(json.dumps(observations,indent=2))
    def trace(value):
        observations['trace'].append(value);save()
    pipeline=TemporalAdmissionPipeline(broker)
    encoding=tiktoken.get_encoding('o200k_base')
    dialogue=RenderedTypedDialogue(StrictTypedDialogue(broker,encoding,trace,model=config['route_model']),encoding)
    def expired(*args):raise TimeoutError('Fresh integration wall bound')
    signal.signal(signal.SIGALRM,expired);signal.alarm(plan['limits']['maximum_wall_seconds'])
    try:
        if len(fixture['sources'])!=28 or len(cases)!=22:raise ValueError('Frozen counts changed')
        for source in fixture['sources']:
            started=time.monotonic();store.put(source);job=store.claim_next()
            if job['source']['id']!=source['id']:raise ValueError('Unexpected worker job')
            claims=pipeline.extract(source,fixture['people'])
            row={'source_id':source['id'],'proposals':[asdict(c) for c in claims],'validation':None}
            observations['sources'].append(row);save()
            row['validation']=pipeline.validate(source,fixture['people'],claims)
            row['committed']=store.complete(job,row['proposals'],row['validation'],fixture['people'])
            row['queryable_lag_ms']=(time.monotonic()-started)*1000;save()
            if not row['committed']:raise ValueError('Source publication failed')
            print(json.dumps({'source':source['id'],'committed':True}),flush=True)
        revision=store.snapshot(fixture['people']).revision;store.close()
        store=TypedMemoryStore(folder/'source.sqlite3');snapshot=store.snapshot(fixture['people'])
        if revision!=snapshot.revision:raise ValueError('Restart changed source snapshot')
        for case in cases:
            started=time.monotonic()
            result=dialogue.respond(case['question'],case['speaker'],snapshot,audience=case['audience'],as_of=case['as_of'])
            observations['cases'].append({'id':case['id'],'result':result,'elapsed_ms':(time.monotonic()-started)*1000})
            save();print(json.dumps({'case':case['id'],'complete':True}),flush=True)
    except Exception as exc:
        observations['errors'].append(type(exc).__name__+': '+str(exc));save()
    finally:
        signal.alarm(0)
        response=httpx.post(broker['base_url']+'/control/disable-paid',headers={'Authorization':'Bearer '+broker['token']},timeout=100)
        response.raise_for_status();(folder/'calls-final.json').write_text(json.dumps(response.json()['calls'],indent=2))
        store.db.execute('PRAGMA wal_checkpoint(TRUNCATE)');store.close();save()
    print(json.dumps({'awaiting_explicit_review':str(folder)}),flush=True)


if __name__=='__main__':run()
