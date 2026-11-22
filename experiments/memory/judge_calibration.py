"""Prospective calibrated scoring control; no engine re-ingestion."""
import argparse
import json
import signal
from experiments.memory.runtime import ROOT,SSD
from experiments.memory.evaluator import evaluate,FIELDS
from tavi.experiment_workflow import begin,finish,audit


def run(protocol):
    import httpx
    folder,plan=begin(protocol,run_root=SSD/'runs/scored');print(json.dumps({'run':str(folder),'audit':audit(folder)}),flush=True)
    data=json.loads((ROOT/'experiments/memory/judge-cases-v1.json').read_text());broker=json.loads((SSD/'private-config/broker.json').read_text())
    results=[];error=None
    def expired(*args):raise TimeoutError('Calibration wall bound reached')
    signal.signal(signal.SIGALRM,expired);signal.alarm(plan['limits']['maximum_wall_seconds'])
    try:
        for repeat,cases in enumerate((data['cases'],list(reversed(data['cases'])))):
            for case in cases:
                result=evaluate(case['question'],case['oracle'],data['episodes'],case['answer'],case['context'],data['people'],broker)
                mismatch={k:{'gold':case['gold'][k],'actual':result[k]} for k in FIELDS if result[k]!=case['gold'][k]}
                results.append({'case_id':case['id'],'repeat':repeat+1,'label':result,'mismatches':mismatch})
                (folder/'observations.json').write_text(json.dumps(results,indent=2))
                print(json.dumps({'case':case['id'],'repeat':repeat+1,'mismatches':mismatch}),flush=True)
    except Exception as exc:error=type(exc).__name__+': '+str(exc)
    finally:
        signal.alarm(0)
        r=httpx.post(broker['base_url']+'/control/disable-paid',headers={'Authorization':'Bearer '+broker['token']},timeout=100);r.raise_for_status()
        calls=r.json()['calls'];(folder/'calls-final.json').write_text(json.dumps(calls,indent=2))
    metrics={'judgments_completed':len(results),'exact_gold_matches':sum(not r['mismatches'] for r in results),
        'safety_label_mismatches':sum(k in r['mismatches'] for r in results for k in ('privacy_violation','identity_error','unsupported_strong_pattern_claim')),
        'additional_api_usd':sum(c.get('actual_micro_usd',c['reserved_micro_usd']) for c in calls)/1e6}
    result=finish(folder,metrics,artifacts=[folder/'observations.json',folder/'calls-final.json'],completed=error is None,error=error)
    print(json.dumps({'run':str(folder),'metrics':metrics,'audit':audit(folder)}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('protocol');run(p.parse_args().protocol)
