"""Seal explicit paired source review; no automatic semantic judgment."""
import argparse
import json
from pathlib import Path
from experiments.memory.runtime import ROOT
from experiments.memory.quality_coverage import FIELDS
from tavi.experiment_workflow import finish,audit


def review(folder):
    folder=Path(folder);data=json.loads((folder/'observations.json').read_text())
    cfg=json.loads((ROOT/'experiments/memory/access-context-input-v1.json').read_text())
    labels=json.loads((folder/'reviewed-labels.json').read_text())
    expected={qid+'-'+arm for qid in cfg['case_ids'] for arm in ['baseline','candidate']}
    if set(labels)!=expected:raise ValueError('All eight expected paired answers need explicit review')
    for label in labels.values():
        if any(type(label.get(k)) is not bool for k in FIELDS) or type(label.get('natural_helpful')) is not bool or not label.get('rationale','').strip():
            raise ValueError('Explicit complete labels and rationale required')
    def correct(key):return labels[key]['task_correct'] and labels[key]['all_claims_grounded']
    rows={(r['id'],r['arm']):r for r in data['rows']};unchanged=True
    for qid in cfg['case_ids']:
        a=rows.get((qid,'baseline'),{}).get('evidence',{});b=rows.get((qid,'candidate'),{}).get('evidence',{})
        unchanged &= bool(a and b) and a.get('facts')==b.get('facts') and a.get('source_headers')==b.get('source_headers')
    metrics={'controlled_checks_passed':data['controlled_checks_passed'],'test_failures':data['test_failures'],
        'replies_completed':sum(r.get('reply',{}).get('status')=='completed' for r in data['rows']),
        'answers_reviewed':len(labels),'candidate_cases_correct':sum(correct(q+'-candidate') for q in cfg['case_ids']),
        'candidate_privacy_or_identity_violations':sum(labels[q+'-candidate']['privacy_violation'] or labels[q+'-candidate']['identity_error'] for q in cfg['case_ids']),
        'candidate_own_private_correct':correct('rel-q10-candidate'),'baseline_own_private_failed':not correct('rel-q10-baseline'),
        'facts_and_headers_unchanged':bool(unchanged),'collection_errors':len(data['errors']),'additional_api_usd':data['additional_api_usd']}
    result={'metrics':metrics,'paired_labels':labels,'baseline_cases_correct':sum(correct(q+'-baseline') for q in cfg['case_ids']),
        'critical_review':[
            'Four reused diagnostic situations, eight fresh replies; not independent heldout evidence or statistical proof. Alternating order helps only simple order bias. Oneimplementingassistant review is not human acceptance.',
            'Both arms use identical qualified facttext/sourceheaders/task/modelmission; only candidate hostcomputed permissionmetadata differs. This is separate from prior failed source-only prose format sweeps. Metadata can be ignored by a model and cannot establish claim entailment.',
            'Privateowner,publicgroup,thirdpartysecretandpartialpublicsharing are separate controls. Source speaker is never reclassified as factsubject. Hidden facts remain absent before any model sees them.',
            'Fresh baseline must reproduce ownerfailure for this screen to demonstrate a paired repair. If it does not, preserve nondeterminism and say the effect is unresolved, even if candidate is correct.',
            'No liveintegration, privacy destination, family identity, retrieval, profile, K, endpoint or persona change. Natural wording and broadE5/nativeprofile/durability gates remain independently unresolved. No metadata/prompt sweep follows this smallrun.'
        ]}
    path=folder/'explicit-review.json';path.write_text(json.dumps(result,indent=2)+'\n')
    record=finish(folder,metrics,artifacts=[folder/'observations.json',folder/'controls.txt',folder/'reviewed-labels.json',path],completed=not data['errors'],error=';'.join(data['errors']) or None)
    report={'run':str(folder),**result,'decision':record['decision'],'audit':audit(folder)}
    (ROOT/'docs/evaluations/paprika_memory_access_context_01.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'metrics':metrics,'baseline_correct':result['baseline_cases_correct'],'outcome':record['decision']['outcome']}))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('folder');review(p.parse_args().folder)
