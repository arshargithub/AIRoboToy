"""Read-only aggregation and explicit human/assistant review preparation.

Does not call a model, label a claim, finish a run or select an engine.
"""
import argparse
import json
import math
from pathlib import Path


def p95(values):
    return sorted(values)[math.ceil(len(values)*.95)-1] if values else None


def summary(folder):
    folder=Path(folder);d=json.loads((folder/'observations.json').read_text());queries=d['queries']
    plan=json.loads((folder/'protocol.json').read_text())
    corpus_path=Path(__file__).resolve().parents[2]/plan['configuration']['corpus']
    corpus=json.loads(corpus_path.read_text())
    # Verify reader's corpus matches the run before using it as oracle.
    from tavi.experiment_workflow import digest
    record=json.loads((folder/'run.json').read_text())
    if digest(corpus_path)!=record['input_sha256'][plan['configuration']['corpus']]:
        raise ValueError('Review corpus differs from frozen input')
    calls=json.loads((folder/'calls-final.json').read_text()) if (folder/'calls-final.json').exists() else []
    reviewed=json.loads((folder/'reviewed-labels.json').read_text()) if (folder/'reviewed-labels.json').exists() else {}
    def label(q):return reviewed.get(q['question']['id'],{})
    facts=[q for q in queries if q['question']['category'] in ('factual','correction')]
    corrections=[q for q in queries if q['question']['category']=='correction']
    patterns=[q for q in queries if q['question']['category']=='pattern']
    warranted=[q for q in patterns if corpus['oracle'][q['question']['id']]['warranted']]
    times=[q['context_ready_ms'] for q in queries]
    stats={'episodes_ingested':len(d['ingests']),'questions_answered':len(queries),
        'native_profile_snapshots':len(d['native_profiles']),'engine_errors':len(d['errors']),
        'grounded_factual_answer_rate':sum(label(q).get('task_correct') is True and label(q).get('all_claims_grounded') is True for q in facts)/32,
        'current_fact_correction_rate':sum(label(q).get('task_correct') is True and label(q).get('all_claims_grounded') is True for q in corrections)/20,
        'attribution_audience_disclosures':sum(label(q).get('privacy_violation') is True or label(q).get('identity_error') is True for q in queries),
        'privacy_disclosures':sum(label(q).get('privacy_violation') is True for q in queries),
        'identity_errors':sum(label(q).get('identity_error') is True for q in queries),
        'unsupported_strong_pattern_claims':sum(label(q).get('unsupported_strong_pattern_claim') is True for q in queries),
        'warranted_pattern_recall':sum(label(q).get('warranted_pattern_recalled') is True for q in warranted)/10,
        'grounded_pattern_answer_rate':sum(label(q).get('task_correct') is True and label(q).get('all_claims_grounded') is True for q in patterns)/20,
        'context_p95_ms':p95(times),'warm_context_p95_ms':p95([q['context_ready_ms'] for q in queries if not q['cold_adapter_process']]),
        'cold_adapter_p95_ms':p95([q['context_ready_ms'] for q in queries if q['cold_adapter_process']]),
        'context_budget_violations':sum(q['envelope']['tokens']>1500 for q in queries),
        'facts_queryable_within_30s_rate':sum(i['source_found'] and i['queryable_after_ms']<=30000 for i in d['ingests'])/120,
        'profile_snapshot_p95_ms':p95([p['available_after_query_ms'] for p in d['native_profiles']]),
        'additional_api_usd':sum(c.get('actual_micro_usd',c['reserved_micro_usd']) for c in calls)/1e6,
        'paid_calls':len(calls),
        'native_profile_quality':'requires explicit claim/source/session/withdrawal review; snapshot latency is not profile correctness',
        'scoped_delete_consistent':'requires raw native result and stale-retry review',
        'full_E5_accepted':False}
    if len(reviewed)!=80:
        for key in ('grounded_factual_answer_rate','current_fact_correction_rate','attribution_audience_disclosures','privacy_disclosures','identity_errors','unsupported_strong_pattern_claims','warranted_pattern_recall','grounded_pattern_answer_rate'):stats[key]=None
    stats['answers_explicitly_reviewed']=len(reviewed)
    cases=[]
    for i,q in enumerate(queries):
        l=label(q);qid=q['question']['id']
        if not l.get('task_correct') or not l.get('all_claims_grounded') or l.get('privacy_violation') or l.get('identity_error') or l.get('unsupported_strong_pattern_claim') or i%10==0 or corpus['oracle'][qid].get('explicit_withdrawal'):
            cases.append({'question':q['question'],'oracle':corpus['oracle'][qid],
                'answer':q['answer']['text'],'label':l,'context':json.loads(q['envelope']['context'])})
    return {'run':str(folder),'statistics_source_review_required':stats,'review_cases':cases,'errors':d['errors']}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('folder');p.add_argument('--compact',action='store_true');a=p.parse_args()
    result=summary(a.folder)
    if a.compact:
        for c in result['review_cases']:c.pop('context')
    print(json.dumps(result,indent=2))
