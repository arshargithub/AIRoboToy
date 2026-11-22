"""Synthetic accounting controls only; no inference, audio or positive identity evidence."""
import io
import json
import time
import unittest
from experiments.memory.runtime import ROOT,SSD,require_ssd
from tavi.experiment_workflow import begin,audit,finish
from tests.test_identity_metrics import fixtures,evaluate,MODEL


def run():
    require_ssd();folder,plan=begin(ROOT/'experiments/speaker-id/identity-metrics-protocol-v1.json',run_root=SSD/'runs/scored')
    print(json.dumps(audit(folder)),flush=True);start=time.monotonic();errors=[]
    stream=io.StringIO();tests=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromName('tests.test_identity_metrics'))
    (folder/'controls.txt').write_text(stream.getvalue())
    rows,enrollment=fixtures();complete=evaluate(rows,model_sha256=MODEL,enrollment=enrollment)
    partial=evaluate(rows[:25],model_sha256=MODEL,enrollment=enrollment[:1])
    if time.monotonic()-start>plan['limits']['maximum_wall_seconds']:errors.append('wall_limit')
    metrics={'controlled_checks_passed':tests.testsRun-len(tests.failures)-len(tests.errors),'test_failures':len(tests.failures)+len(tests.errors),
        'partial_collection_stays_pending':partial['identity_subscreen']=='needs_evidence',
        'complete_fixture_cannot_accept_E4':complete['identity_subscreen']=='pass' and not complete['E4_accepted'] and not complete['authorizes_personal_memory'] and not complete['recognition_enabled'],
        'collection_errors':len(errors),'additional_api_usd':0.0}
    (folder/'observations.json').write_text(json.dumps({'metrics':metrics,'partial_synthetic':partial,'complete_synthetic':complete,'errors':errors},indent=2)+'\n')
    record=finish(folder,metrics,artifacts=[folder/'controls.txt',folder/'observations.json'],completed=not errors,error=';'.join(errors) or None)
    report={'run':str(folder),'metrics':metrics,'decision':record['decision'],'audit':audit(folder),'critical_review':[
        'Ten deterministic synthetic accounting controls, not actual voice recognition or family evidence. Fixtures use stable family IDs as proxies; no recorded child voice or inferred identity is supplied.',
        'Eligibility/person/unknown/overlap labels and enrollment/development metadata must be independently frozen and truthful. Hash/session checks detect declared reuse, not fabricated labels, acoustically duplicated re-encodings, or proof of consent.',
        'Known abstention reduces coverage/accuracy; removing poor recordings cannot disappear attempted counts. Wrong-known assignment denominator stays eligibleknown; the allcases rate is reported separately to reveal dilution.',
        'Original E4 identity minimums and rates retained. Combined20short/overlap requires both kinds represented as a completeness guard, not a new calibrated threshold. Short rejection reported separately; no automated overlap detector qualified.',
        'Partial single-person data is needs_evidence, never falsely accepted or forced to wait for simultaneous family availability. Complete identitysubscreen still cannot pass fullE4: groups, followups, sideconversations and closure remain required.',
        'No threshold selection/calibration/search, profile scanning/loading, encoder/live controller integration, memory authorization or production changes. Unknown/audience policy and held-out household accuracy remain open.'
    ]}
    (ROOT/'docs/evaluations/paprika_identity_metrics_01.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'metrics':metrics,'outcome':record['decision']['outcome'],'run':str(folder)}),flush=True)


if __name__=='__main__':run()
