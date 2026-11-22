"""Experimental pre-inference source boundary, not semantic validation.

Source records must come from the authoritative local ledger, never from a
model response. Drop a whole derived assertion if any supporting source is
unqualified. Never edit its text or repair its provenance by removing IDs.
"""
from copy import deepcopy
from experiments.memory.guarded_worker import source_rejection


def qualify_context(task, evidence, sources):
    people, audience = task['people'], task['audience_ids']
    if (not audience or len(audience) != len(set(audience))
            or not set(audience) <= set(people)
            or task['actual_speaker_id'] not in audience):
        raise ValueError('Unqualified identity or audience')
    ledger = {}
    for source in sources:
        sid = source['id']
        if sid in ledger:
            raise ValueError('Ambiguous canonical source ID')
        ledger[sid] = source
    kept, rejected, original_indices = [], [], []
    for index, fact in enumerate(evidence['facts']):
        ids = fact.get('sources')
        reason = None
        if (not isinstance(ids, list) or not ids or fact.get('unresolved_support')
                or any(not isinstance(s, str) or s not in ledger for s in ids)):
            reason = 'unbound_support'
        elif any(source_rejection(ledger[s], people) or ledger[s].get('deleted')
                 or ledger[s].get('quarantined') for s in ids):
            reason = 'unqualified_support'
        elif any(not set(audience) <= set(ledger[s]['audience_ids']) for s in ids):
            reason = 'audience_not_allowed'
        if reason:
            rejected.append({'original_index': index, 'reason': reason})
        else:
            kept.append(deepcopy(fact)); original_indices.append(index)
    headers = {s: {'speaker_id': ledger[s]['speaker_id'],
                   'session_id': ledger[s]['session'], 'at': ledger[s]['at']}
               for fact in kept for s in fact['sources']}
    return {'evidence': {'source_headers': headers, 'facts': kept},
            'rejected': rejected, 'original_indices': original_indices,
            'semantic_grounding_verified': False}
