"""Explicit source-paired labels seal a diagnostic; never label with another model."""
import argparse
import json
from pathlib import Path
from experiments.memory.runtime import ROOT
from experiments.memory.quality_coverage import summarize
from tavi.experiment_workflow import finish,audit


def review(folder):
    folder=Path(folder);result=json.loads((folder/'observations.json').read_text())
    data=json.loads((ROOT/'experiments/memory/reliability-input-v1.json').read_text())
    oracle=json.loads((ROOT/'experiments/memory/reliability-oracle-v1.json').read_text())['cases']
    labels=json.loads((folder/'reviewed-labels.json').read_text())
    rows=result['cases'];queries=[{'question':r['question'],'answer':r.get('reply',{})} for r in rows]
    coverage=summarize({'questions':data['cases']},queries,labels)
    for label in labels.values():
        if type(label.get('natural_helpful')) is not bool:raise ValueError('Separate conversational usefulness label required')
    positive=next(r for r in rows if r['id']=='rel-q17') if any(r['id']=='rel-q17' for r in rows) else None
    headers=positive.get('boundary',{}).get('evidence',{}).get('source_headers',{}) if positive else {}
    support=oracle['rel-q17']['support_ids'];own=[headers[s] for s in support if s in headers and headers[s]['speaker_id']=='a']
    context_leaks=[]
    for r in rows:
        material=json.dumps(r.get('boundary',{}).get('evidence',{}))
        for canary in oracle[r['id']].get('forbidden',[]):
            if '-' in canary and canary in material:context_leaks.append({'id':r['id'],'canary':canary})
    metrics={'source_attempts':len(result['ingests']),'sources_completed':sum(not r['native'].get('quarantined',False) for r in result['ingests']),
        'unknown_quarantined':sum(r['native'].get('quarantined',False) for r in result['ingests']),
        'replies_completed':sum(r.get('reply',{}).get('status')=='completed' for r in rows),
        'answers_reviewed':coverage['reviewed'],
        'all_case_task_grounding_correct':coverage['all_question_task_and_grounding']['correct'],
        'natural_helpful_replies':sum(l['natural_helpful'] for l in labels.values()),
        'correction_cases_correct':sum(labels.get(f'rel-q{i:02}',{}).get('task_correct') is True and labels.get(f'rel-q{i:02}',{}).get('all_claims_grounded') is True for i in range(1,5)),
        'privacy_or_identity_violations':sum(l['privacy_violation'] or l['identity_error'] for l in labels.values()),
        'unsupported_strong_patterns':sum(l['unsupported_strong_pattern_claim'] for l in labels.values()),
        'positive_pattern_three_sessions':len({h['session_id'] for h in own})>=3,
        'private_input_canary_leaks':len(context_leaks),'local_listen_only_replies':sum(r.get('route')=='existing_local_listen_only' for r in rows),
        'collection_errors':len(result['errors']),'additional_api_usd':result['additional_api_usd']}
    review={'metrics':metrics,'coverage':coverage,'context_leaks':context_leaks,'source_paired_labels':labels,
        'critical_review':[
            '24new authored fictional cases/28source attempts are a focused development screen, not the120/80/20/three-repetition E5 comparison or realfamily evidence. Oneimplementing assistant authored and reviewed; no independent human/product acceptance.',
            'Everycase including privacy-safe abstention, attribution, comfort and patterns remains in the overall denominator. Category rates, missingreviews and task/grounding versus naturalhelpfulness stay separate. No exactsuggestion/title matching or automatedsemanticjudge.',
            'Current Hindsight recall/1500token canonical qualification and unchanged native text mission are reused. Native support IDs establish provenance eligibility, not entailment; review checks actual source texts and visible evidence. No rawsource supplementation repairs missedretrieval.',
            'One supported explicit listen-only command takes existing local acknowledgement without paid lookup/reply; other quiet-company wording remains a measured native case. This is current controller boundary behaviour, not a new prompt repair.',
            'One earlyquery precedes corrections; laterqueries use finalsourceview. Independent sessions and same-session repetitions are controlled metadata. No automatic pattern threshold was tuned from outputs.',
            'One configuration, bounded paid calls, reservations retained for ambiguous failures, extractor disabled before bulk replies; no paid retries/prompt sweeps. No audio/K/microphone/cloudmemoryhosting or household identity changes.',
            'Timing, cold-start/loaded retrieval, nativeprofile validity, longrunning recovery and finalengine choice are not accepted by this functional screen.'
        ]}
    path=folder/'explicit-review.json';path.write_text(json.dumps(review,indent=2)+'\n')
    record=finish(folder,metrics,artifacts=[folder/'observations.json',folder/'reviewed-labels.json',path],completed=not result['errors'],error=';'.join(result['errors']) or None)
    report={'run':str(folder),**review,'decision':record['decision'],'audit':audit(folder)}
    (ROOT/'docs/evaluations/paprika_memory_reliability_01.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'metrics':metrics,'outcome':record['decision']['outcome']}))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('folder');review(p.parse_args().folder)
