"""Experimental canonical-source context, not enabled in the live application.

Native memory assertions nominate sources; their prose never becomes answer
evidence. This changes the comparison contract and needs a new protocol. It
does not verify retrieval relevance or turn a citation into an entailed claim.
"""
from datetime import datetime
import json

from experiments.memory.context_envelope import native_facts


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('An explicit timezone is required')
    return parsed


def pack_sources(engine, native, episodes, audience, encoding, *, as_of,
                 deleted_source_ids, maximum_tokens=1500):
    """Pack complete original utterances from eligible nominated source IDs.

The caller supplies the authoritative source/tombstone view at the query
boundary. An uncertain journal generation must still block the query upstream.
No semantic inference, source supplementation, or cross-person profile merge
occurs here. A wrong native source ID may result in irrelevant evidence.
    """
    if not audience or not 1 <= maximum_tokens <= 1500:
        raise ValueError('Explicit audience and a valid context budget required')
    cutoff = timestamp(as_of)
    ledger = {e['id']: e for e in episodes}
    if len(ledger) != len(episodes):
        raise ValueError('Canonical source IDs must be unique')
    deleted = set(deleted_source_ids)
    groups, seen, rejected = {}, set(), []
    for hint in native_facts(engine, native):
        ids = hint['sources']
        reason = None
        if hint.get('unresolved_support') or not ids or any(s not in ledger for s in ids):
            reason = 'unbound_source'
        elif any(s in deleted for s in ids):
            reason = 'deleted_source'
        elif any(timestamp(ledger[s]['at']) > cutoff for s in ids):
            reason = 'future_source'
        elif any(not set(audience) <= set(ledger[s]['audience_ids']) for s in ids):
            reason = 'audience_not_allowed'
        if reason:
            rejected.append({'sources': ids, 'reason': reason})
            continue
        for sid in ids:
            if sid in seen:
                continue
            seen.add(sid)
            scope = tuple(sorted(ledger[sid]['audience_ids']))
            groups.setdefault(scope, []).append(sid)

    def envelope(ids):
        return {
            'source_headers': {
                sid: {'speaker_id': ledger[sid]['speaker_id'],
                      'session_id': ledger[sid]['session'], 'at': ledger[sid]['at']}
                for sid in ids},
            'facts': [{'text': ledger[sid]['text'], 'sources': [sid],
                       'kind': 'verbatim_utterance', 'lineage': 'canonical_source'}
                      for sid in ids],
        }

    def encode(ids):
        return json.dumps(envelope(ids), ensure_ascii=False, separators=(',', ':'))

    if len(encoding.encode(encode([]))) > maximum_tokens:
        raise ValueError('Even an empty context exceeds its budget')
    queues = [groups[scope] for scope in sorted(groups)]
    chosen, omitted = [], []
    for index in range(max(map(len, queues), default=0)):
        for queue in queues:
            if index >= len(queue):
                continue
            sid = queue[index]
            if len(encoding.encode(encode(chosen + [sid]))) <= maximum_tokens:
                chosen.append(sid)
            else:
                # Never truncate a correction, negation or private attribution.
                omitted.append(sid)
    encoded = encode(chosen)
    return {'context': encoded, 'tokens': len(encoding.encode(encoded)),
            'selected_source_ids': chosen, 'omitted_source_ids': omitted,
            'rejected': rejected, 'representation': 'canonical_utterances_only'}
