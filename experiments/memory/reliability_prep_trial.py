"""Controlled collector/fixture qualification, zero real native or paid work."""
import io
import json
import time
import unittest
from experiments.memory.runtime import ROOT,SSD,require_ssd
from experiments.memory.build_reliability_cases import validate
from tavi.experiment_workflow import begin,audit,finish


def run():
    require_ssd();folder,plan=begin(ROOT/'experiments/memory/reliability-prep-protocol-v1.json',run_root=SSD/'runs/scored')
    print(json.dumps(audit(folder)),flush=True);start=time.monotonic();errors=[]
    data=json.loads((ROOT/'experiments/memory/reliability-input-v1.json').read_text())
    gold=json.loads((ROOT/'experiments/memory/reliability-oracle-v1.json').read_text());shape=validate(data,gold)
    suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromName(m) for m in ['tests.test_reliability_cases','tests.test_reliability_trial','tests.test_quality_coverage']])
    stream=io.StringIO();tests=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    (folder/'controls.txt').write_text(stream.getvalue())
    if time.monotonic()-start>plan['limits']['maximum_wall_seconds']:errors.append('wall_limit')
    metrics={'python_checks_passed':tests.testsRun-len(tests.failures)-len(tests.errors),'test_failures':len(tests.failures)+len(tests.errors),
        'source_attempts':shape['episodes'],'cases':shape['cases'],'public_oracle_separation':shape['all_model_queries_exclude_oracle'],
        'collection_errors':len(errors),'additional_api_usd':0.0}
    (folder/'observations.json').write_text(json.dumps({'metrics':metrics,'shape':shape,'errors':errors,'real_inference':False},indent=2)+'\n')
    record=finish(folder,metrics,artifacts=[folder/'controls.txt',folder/'observations.json'],completed=not errors,error=';'.join(errors) or None)
    report={'run':str(folder),'metrics':metrics,'decision':record['decision'],'audit':audit(folder),
        'critical_review':['15controlled tests qualify labels/accounting/modelpayload/route/budget-phase semantics only, not real extraction/retrieval/reply quality or human acceptance.',
        'Oneimplementingassistant authored cases/oracles; no independenthousehold distribution or fullE5/20pattern/three-repeat claim. Positivefixturedecisions are synthetic and do not enable identity.',
        'Private canary initially present in an authored publicfictionalquote was removed beforefreezing; a regression rejects that confounded label. Explicit listen-only phrase uses existing supported route, not a newregex or prompt.',
        'New case content is freshauthored but shares deliberate failurecategories with prior development. No broaderengine ranking, liveK/default change or familyrecording implied.']}
    (ROOT/'docs/evaluations/paprika_reliability_prep_01.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'metrics':metrics,'outcome':record['decision']['outcome']}),flush=True)


if __name__=='__main__':run()
