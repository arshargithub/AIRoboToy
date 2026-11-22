"""Experimental deterministic projection over separately admitted claims.

Not live and NOT an automatic entailment validator. Extraction proposals do
not authorize themselves: admission digests must come from a separately qualified
review/validation boundary. Tests use manually admitted fictional claims.
Canonical sources, rather than extracted metadata, supply speaker, audience,
session and event time. Unknown or conflicting evidence yields abstention.
"""
from dataclasses import asdict, dataclass
import hashlib
import json

from experiments.memory.source_context import timestamp


@dataclass(frozen=True)
class Claim:
    id: str
    source_id: str
    subject_id: str
    slot: str
    value: str
    kind: str  # preference, choice, withdraw, resume, event
    relation: str  # self or reported; reported needs separate admission too
    quote: str


def admission_digest(claim, source):
    """Bind a separate admission decision to exact claim AND source contents."""
    encoded = json.dumps({'claim': asdict(claim), 'source': source},
                         sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def eligible(claims, sources, admissions, *, subject, slot, audience, as_of,
             deleted_source_ids=()):
    if not subject or subject == 'unknown' or not slot or not audience:
        return []
    cutoff = timestamp(as_of)
    ledger = {s['id']: s for s in sources}
    if len(ledger) != len(sources):
        raise ValueError('Ambiguous canonical source IDs')
    unique = {}
    for claim in claims:
        if claim.id in unique and unique[claim.id] != claim:
            raise ValueError('Conflicting claim ID; quarantine projection')
        unique[claim.id] = claim
    result = []
    for claim in unique.values():
        if claim.id not in admissions or claim.subject_id != subject or claim.slot != slot:
            continue
        source = ledger.get(claim.source_id)
        if (source is None or claim.source_id in deleted_source_ids
                or source['speaker_id'] == 'unknown'
                or not set(audience) <= set(source['audience_ids'])
                or timestamp(source['at']) > cutoff):
            continue
        if admissions[claim.id] != admission_digest(claim, source):
            continue
        if claim.kind not in {'preference', 'choice', 'withdraw', 'resume', 'event'}:
            raise ValueError('Unknown claim kind')
        if claim.relation not in {'self', 'reported'}:
            raise ValueError('Explicit subject relation required')
        if claim.relation == 'self' and source['speaker_id'] != subject:
            continue
        # Exact support is necessary, but does not prove semantic entailment.
        if not claim.quote or claim.quote not in source['text']:
            continue
        result.append((claim, source))
    return result


def preference(claims, sources, admissions, **scope):
    evidence = eligible(claims, sources, admissions, **scope)
    rows = [(c, s) for c, s in evidence if c.kind == 'preference']
    if not rows:
        return {'status': 'unknown', 'source_ids': []}
    newest = max(timestamp(s['at']) for _, s in rows)
    latest = [(c, s) for c, s in rows if timestamp(s['at']) == newest]
    values = {c.value for c, _ in latest}
    ids = sorted({s['id'] for _, s in latest})
    if len(values) != 1:
        return {'status': 'conflict', 'source_ids': ids}
    value = values.pop()
    withdrawals = [s for c, s in evidence if c.kind == 'withdraw'
                   and c.value == value and timestamp(s['at']) >= newest]
    if withdrawals:
        # Do not silently revive an older superseded preference either.
        return {'status': 'withdrawn', 'source_ids': sorted({s['id'] for s in withdrawals})}
    return {'status': 'supported', 'subject_id': scope['subject'],
            'slot': scope['slot'], 'value': value, 'source_ids': ids,
            'observed_at': newest.isoformat()}


def pattern(claims, sources, admissions, *, activity, **scope):
    rows = [(c, s) for c, s in eligible(claims, sources, admissions, **scope)
            if c.value == activity and c.kind in {'choice', 'withdraw', 'resume'}]
    controls = [(c, s) for c, s in rows if c.kind in {'withdraw', 'resume'}]
    since = None
    if controls:
        latest = max(timestamp(s['at']) for _, s in controls)
        current = [(c, s) for c, s in controls if timestamp(s['at']) == latest]
        # A simultaneous conflicting resumption cannot undo withdrawal.
        if any(c.kind == 'withdraw' for c, _ in current):
            return {'status': 'withdrawn', 'source_ids': sorted({s['id'] for _, s in current})}
        since = latest
    evidence = {s['id']: s for c, s in rows if c.kind == 'choice'
                and (since is None or timestamp(s['at']) > since)}
    sessions = sorted({s['session'] for s in evidence.values() if s['session']})
    # Never let claims or repeated writes masquerade as independent sessions.
    return {'status': 'tentative' if len(sessions) >= 3 else 'insufficient_sessions',
            'subject_id': scope['subject'], 'activity': activity,
            'source_ids': sorted(evidence), 'session_ids': sessions,
            'session_count': len(sessions)}
