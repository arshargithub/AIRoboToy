"""Experimental host-computed permission metadata, not a new memory permission.

Re-run the existing canonical filter first. No fact text, subject, audience scope
or unknown identity can be repaired or authorized by a model-produced header.
"""
from copy import deepcopy
from experiments.memory.reply_boundary import qualify_context


def with_access_decision(task,evidence,sources):
    boundary=qualify_context(task,evidence,sources)
    ledger={s['id']:s for s in sources};context=deepcopy(boundary['evidence'])
    speaker=task['actual_speaker_id'];people=task['people'];audience=task['audience_ids']
    if any(not isinstance(people[p],str) or not people[p].strip() for p in audience):
        raise ValueError('Trusted display names required')
    context['app_access_decision']={
        'scope':'included_evidence_only',
        'current_speaker':{'id':speaker,'name':people[speaker]},
        'current_listeners':[{'id':p,'name':people[p]} for p in audience],
        'all_included_facts_allowed_for_current_audience':True,
        'complete_memory_search_guaranteed':False,
        'semantic_truth_verified':False,
        'source_permissions':{sid:{'source_speaker_id':ledger[sid]['speaker_id'],
            'permitted_audience_ids':deepcopy(ledger[sid]['audience_ids']),
            'allowed_for_current_audience':True} for sid in context['source_headers']}}
    return {**boundary,'evidence':context}
