"""Fresh native pre-ingestion boundary screen, preserving complete episodes."""
import json,signal,time
from experiments.memory.runtime import ROOT,SSD,require_ssd
from experiments.memory.pilot import Process
from tavi.experiment_workflow import begin,audit

def run():
    import httpx
    require_ssd();p,plan=begin(ROOT/'experiments/memory/native-guard-protocol-v1.json',run_root=SSD/'runs/scored')
    print(json.dumps({'run':str(p),'audit':audit(p)}),flush=True)
    f=json.loads((ROOT/'experiments/memory/native-guard-input-v1.json').read_text());broker=json.loads((SSD/'private-config/broker.json').read_text())
    logs=p/'logs';logs.mkdir();worker=None;o={'ingests':[],'queries':[],'errors':[]}
    def save():(p/'observations.json').write_text(json.dumps(o,indent=2))
    def send(r):
        v=worker.send(r,timeout=420)
        if not v['ok']:raise RuntimeError(v['error'])
        return v['result']
    def expired(*args):raise TimeoutError('Native guard wall bound')
    signal.signal(signal.SIGALRM,expired);signal.alarm(plan['limits']['maximum_wall_seconds'])
    try:
        worker=Process('hindsight',SSD/'databases'/p.parent.name/p.name,logs,'guarded_worker.py');send({'op':'initialize'})
        for e in f['episodes']:
            result=send({'op':'ingest','episode':e,'people':f['people']});o['ingests'].append({'id':e['id'],'result':result});save()
            print(json.dumps({'source':e['id'],'quarantined':result.get('quarantined',False)}),flush=True)
        # Restart before reads: quarantine must not leak through native replay.
        worker.stop();worker=Process('hindsight',SSD/'databases'/p.parent.name/p.name,logs,'guarded_worker.py');send({'op':'initialize'})
        for q in f['queries']:
            start=time.monotonic();result=send({'op':'query','question':q,'people':f['people']})
            o['queries'].append({'id':q['id'],'result':result,'elapsed_ms':(time.monotonic()-start)*1000});save()
    except Exception as exc:o['errors'].append(type(exc).__name__+': '+str(exc));save()
    finally:
        signal.alarm(0)
        r=httpx.post(broker['base_url']+'/control/disable-paid',headers={'Authorization':'Bearer '+broker['token']},timeout=100);r.raise_for_status()
        (p/'calls-final.json').write_text(json.dumps(r.json()['calls'],indent=2))
        if worker:worker.stop()
        save()
    print(json.dumps({'awaiting_review':str(p),'errors':o['errors']}),flush=True)

if __name__=='__main__':run()
