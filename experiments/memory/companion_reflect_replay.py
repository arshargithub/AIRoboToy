"""One diagnosis-driven replay; same native banks/tasks, corrected effective budget."""
import json,signal,time
from experiments.memory.runtime import ROOT,SSD,require_ssd
from experiments.memory.pilot import Process
from tavi.experiment_workflow import begin,audit


def run():
    import httpx
    require_ssd()
    p,plan=begin(ROOT/'experiments/memory/companion-reflect-protocol-v2.json',run_root=SSD/'runs/scored')
    print(json.dumps({'run':str(p),'audit':audit(p)}),flush=True)
    config=plan['configuration'];old=json.loads(open(config['observations']).read());fixture=json.loads((ROOT/'experiments/memory/companion-input-v1.json').read_text())
    cases={c['id']:c for c in json.loads((ROOT/'experiments/memory/companion-cases-v1.json').read_text())}
    broker=json.loads((SSD/'private-config/broker.json').read_text());logs=p/'logs';logs.mkdir()
    worker=None;obs={'cases':[],'errors':[]}
    def save():(p/'observations.json').write_text(json.dumps(obs,indent=2))
    def send(req):
        r=worker.send(req,timeout=420)
        if not r['ok']:raise RuntimeError(r['error'])
        return r['result']
    def expired(*args):raise TimeoutError('Reflection replay wall bound')
    signal.signal(signal.SIGALRM,expired);signal.alarm(plan['limits']['maximum_wall_seconds'])
    try:
        worker=Process('hindsight',__import__('pathlib').Path(config['database']),logs,'companion_worker.py');send({'op':'initialize'})
        for previous in old['cases']:
            if previous['arm']!='hindsight_reflect' or previous.get('unknown_identity_no_memory_fallback'):continue
            case=cases[previous['case_id']];start=time.monotonic()
            r=send({'op':'reflect','question':case,'people':fixture['people'],'task':previous['task']})
            row={'case_id':case['id'],'text':r['native']['text'],'reflection':r,'elapsed_ms':(time.monotonic()-start)*1000}
            obs['cases'].append(row);save()
            if not r['native'].get('trace',{}).get('tool_calls'):
                raise RuntimeError('Native reflection again performed no tool search; preserve and stop')
            print(json.dumps({'case':case['id'],'complete':True,'tool_calls':len(r['native']['trace']['tool_calls'])}),flush=True)
    except Exception as exc:obs['errors'].append(type(exc).__name__+': '+str(exc));save()
    finally:
        signal.alarm(0)
        r=httpx.post(broker['base_url']+'/control/disable-paid',headers={'Authorization':'Bearer '+broker['token']},timeout=100);r.raise_for_status()
        (p/'calls-final.json').write_text(json.dumps(r.json()['calls'],indent=2))
        if worker:worker.stop()
        save()
    print(json.dumps({'awaiting_explicit_review':str(p),'errors':obs['errors']}),flush=True)


if __name__=='__main__':run()
