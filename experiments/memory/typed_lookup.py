"""Source-bound typed lookup over admitted claims; not a live memory service.

The caller supplies authoritative audience and query time separately from the
typed request. Natural-language target resolution is a separate unqualified
boundary. Semantic rejection can conservatively block a stale preference;
it can never create a replacement fact.
"""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json

from experiments.memory.claim_admission import AdmissionPipeline
from experiments.memory.source_context import timestamp
from experiments.memory.subject_contract import Claim, admission_digest, eligible, preference, pattern


def source_digest(source):
    return hashlib.sha256(json.dumps(source, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class MemorySnapshot:
    def __init__(self, people, sources, processed, *, deleted_source_ids=()):
        self.people = deepcopy(people)
        self.sources = deepcopy(sources)
        self.deleted = frozenset(deleted_source_ids)
        self.ledger = {s['id']: s for s in self.sources}
        if len(self.ledger) != len(self.sources):
            raise ValueError('Ambiguous canonical source IDs')
        self.claims, self.admissions, self.unresolved, self.pending = [], {}, [], []
        seen = set()
        for row in deepcopy(processed):
            sid = row['source_id']
            if sid not in self.ledger or sid in seen:
                raise ValueError('Unknown or duplicate processed source')
            seen.add(sid)
            claims = [Claim(**c) for c in row['proposals']]
            if any(c.source_id != sid for c in claims):
                raise ValueError('Cross-source proposal binding')
            self.claims.extend(claims)
            validation = row['validation']
            if validation is None or row.get('source_sha256') != source_digest(self.ledger[sid]):
                self.pending.append(sid)
                continue
            candidates = {c.id: c for c in claims}
            if not set(validation['admissions']) <= set(candidates):
                raise ValueError('Admission references unknown proposal')
            if any(value != admission_digest(candidates[cid], self.ledger[sid])
                   for cid, value in validation['admissions'].items()):
                self.pending.append(sid)
                continue
            self.admissions.update(validation['admissions'])
            rejected = {d['id'] for d in validation['decisions'] if not d['entailed']}
            for claim in claims:
                if claim.id in rejected and not AdmissionPipeline.structural_error(
                        claim, self.ledger[sid], self.people):
                    self.unresolved.append(claim)
        self.pending.extend(sid for sid in self.ledger if sid not in seen)
        if len({c.id for c in self.claims}) != len(self.claims):
            raise ValueError('Duplicate claim IDs across processed sources')
        body = {'people': self.people, 'sources': self.sources,
                'claims': [asdict(c) for c in self.claims], 'admissions': self.admissions,
                'unresolved': [asdict(c) for c in self.unresolved],
                'pending': sorted(self.pending), 'deleted': sorted(self.deleted)}
        self.revision = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()

    def authorized(self, source, audience, as_of):
        return (source['id'] not in self.deleted and bool(audience)
                and set(audience) <= set(source['audience_ids'])
                and timestamp(source['at']) <= timestamp(as_of))

    def lookup(self, request, *, audience, as_of):
        if set(request) != {'operation', 'subject_id', 'slot'}:
            raise ValueError('Typed requests cannot override audience, time or source state')
        if not audience or not set(audience) <= set(self.people):
            raise ValueError('Explicit known audience required')
        subject, slot, operation = request['subject_id'], request['slot'], request['operation']
        if operation not in {'preference', 'interests', 'events'}:
            raise ValueError('Unknown lookup operation')
        if not isinstance(slot, str) or not slot:
            raise ValueError('Explicit fact slot required')
        result = self._lookup(operation, subject, slot, audience, as_of)
        return {**result, 'subject_id': subject, 'subject_name': self.people.get(subject),
                'snapshot_revision': self.revision}

    def _lookup(self, operation, subject, slot, audience, as_of):
        if subject not in self.people:
            return {'status': 'unknown_identity', 'source_ids': []}
        if any(self.authorized(self.ledger[sid], audience, as_of) for sid in self.pending):
            return {'status': 'pending', 'source_ids': []}
        scope = dict(subject=subject, slot=slot, audience=audience, as_of=as_of,
                     deleted_source_ids=self.deleted)
        rows = eligible(self.claims, self.sources, self.admissions, **scope)
        # An unverified extra choice cannot negate already verified choices.
        # Only a possible state-changing preference/withdrawal/resumption can
        # make a previously current state unsafe to repeat.
        barrier_kinds = {'preference', 'withdraw'} if operation == 'preference' else {'withdraw', 'resume'}
        barriers = [c for c in self.unresolved if c.subject_id == subject and c.slot == slot
                    and c.kind in barrier_kinds
                    and self.authorized(self.ledger[c.source_id], audience, as_of)]
        if operation in {'preference', 'interests'} and barriers:
            relevant = {'preference', 'withdraw'} if operation == 'preference' else {'withdraw', 'resume'}
            resolving_times = [timestamp(s['at']) for c, s in rows if c.kind in relevant]
            barrier_at = max(timestamp(self.ledger[c.source_id]['at']) for c in barriers)
            if not resolving_times or max(resolving_times) < barrier_at:
                return {'status': 'uncertain', 'source_ids': [],
                        'reason': 'Later source unresolved; do not repeat older state as current.'}
        if operation == 'preference':
            return preference(self.claims, self.sources, self.admissions, **scope)
        if operation == 'interests':
            # Candidates originate only in eligible evidence; enumerating every
            # private extracted value would leak it even with zero support.
            activities = sorted({c.value for c, _ in rows
                                 if c.kind in {'choice', 'withdraw', 'resume'}})
            return {'status': 'evaluated', 'patterns': [{'activity': value, **pattern(
                self.claims, self.sources, self.admissions, activity=value, **scope)}
                for value in activities]}
        # Event quotes retain relative dates and original speaker; do not turn
        # a past "yesterday" into yesterday relative to the current query.
        events = []
        for event_slot in sorted({c.slot for c in self.claims if c.kind == 'event'}):
            for claim, source in eligible(self.claims, self.sources, self.admissions,
                                          **{**scope, 'slot': event_slot}):
                if claim.kind == 'event':
                    events.append({'value': claim.value, 'quote': claim.quote,
                                   'reported_at': source['at'], 'speaker_id': source['speaker_id'],
                                   'relation': claim.relation, 'source_id': source['id']})
        unique = {(e['source_id'], e['quote']): e for e in events}
        return {'status': 'supported' if unique else 'unknown',
                'events': sorted(unique.values(), key=lambda e: timestamp(e['reported_at']), reverse=True)}
