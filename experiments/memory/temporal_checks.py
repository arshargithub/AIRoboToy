"""Zero-paid native dependency contract check; no active-service mutation.

Run only between scored engine trials to avoid CPU contention with timings.
"""
import argparse
from datetime import datetime,timezone
import json
import signal
import time
from experiments.memory.runtime import ROOT,SSD
from experiments.memory.hindsight_compat import english_query_analyzer
from tavi.experiment_workflow import begin,finish,audit


def run(protocol):
    folder,plan=begin(protocol,run_root=SSD/'runs/scored');print(json.dumps({'run':str(folder),'audit':audit(folder)}),flush=True)
    from hindsight_api.engine.query_analyzer import DateparserQueryAnalyzer
    cases=json.loads((ROOT/'experiments/memory/temporal-cases-v1.json').read_text())
    results=[];error=None
    reference=datetime(2026,3,20,tzinfo=timezone.utc)
    def expired(*args):raise TimeoutError('Local temporal qualification deadline')
    signal.signal(signal.SIGALRM,expired);signal.alarm(120)
    try:
        for mode,analyzer in [('native_en',DateparserQueryAnalyzer(languages=['en'])),('candidate_en',english_query_analyzer())]:
            start=time.monotonic();analyzer.load();load_ms=(time.monotonic()-start)*1000
            for case in cases:
                began=time.monotonic();exception=None;constraint=None
                try:
                    value=analyzer.analyze(case['query'],reference)
                    if value.temporal_constraint:
                        constraint=[value.temporal_constraint.start_date.isoformat(),value.temporal_constraint.end_date.isoformat()]
                except Exception as exc:exception=type(exc).__name__+': '+str(exc)
                passed=exception is None and (constraint is None if case['expected']=='none' else constraint is not None and all(d.startswith(case['expected']) for d in constraint))
                results.append({'mode':mode,'case':case,'constraint':constraint,'exception':exception,'matches_expected':passed,
                    'load_ms':load_ms,'analysis_ms':(time.monotonic()-began)*1000})
        (folder/'observations.json').write_text(json.dumps(results,indent=2))
    except Exception as exc:error=type(exc).__name__+': '+str(exc)
    finally:signal.alarm(0)
    (folder/'observations.json').write_text(json.dumps(results,indent=2))
    metrics={'candidate_correct':sum(r['matches_expected'] for r in results if r['mode']=='candidate_en'),
        'native_contract_failures_observed':sum(r['exception'] is not None for r in results if r['mode']=='native_en'),
        'candidate_exceptions':sum(r['exception'] is not None for r in results if r['mode']=='candidate_en'),'additional_api_usd':0}
    finish(folder,metrics,artifacts=[folder/'observations.json'],completed=error is None,error=error)
    print(json.dumps({'run':str(folder),'metrics':metrics,'audit':audit(folder)}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('protocol');run(p.parse_args().protocol)
