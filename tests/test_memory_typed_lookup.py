from copy import deepcopy
from dataclasses import asdict
import unittest

from experiments.memory.subject_contract import Claim, admission_digest
from experiments.memory.typed_lookup import MemorySnapshot, source_digest


class TypedLookupTests(unittest.TestCase):
    def setUp(self):
        self.sources, self.rows = [], []
        self.people = {'a': 'Ari', 'b': 'Bo'}
        self.query = {'operation': 'preference', 'subject_id': 'a', 'slot': 'drink'}

    def add(self, value, *, subject='a', kind='preference', slot='drink', day=1,
            audience=('a', 'b'), session=None, accepted=True, pending=False):
        sid = f's{len(self.sources)}'
        source = {'id': sid, 'speaker_id': subject, 'session': session or sid,
                  'at': f'2026-01-{day:02}T12:00:00Z', 'audience_ids': list(audience),
                  'text': f'I {kind} {value} yesterday.'}
        claim = Claim(sid+':0', sid, subject, slot, value, kind, 'self', source['text'])
        self.sources.append(source)
        self.rows.append({'source_id': sid, 'source_sha256': source_digest(source),
                          'proposals': [asdict(claim)], 'validation': None if pending else {
                              'admissions': {claim.id: admission_digest(claim, source)} if accepted else {},
                              'decisions': [{'id': claim.id, 'entailed': accepted, 'reason': 'Fixture decision'}],
                              'rejected': {} if accepted else {claim.id: 'Fixture rejection'}}})

    def snapshot(self, **kwargs):
        return MemorySnapshot(self.people, self.sources, self.rows, **kwargs)

    def lookup(self, *, query=None, audience=('a',), as_of='2026-02-01T12:00:00Z', **kwargs):
        return self.snapshot(**kwargs).lookup(query or self.query, audience=list(audience), as_of=as_of)

    def test_later_unresolved_change_blocks_stale_preference_until_resolved(self):
        self.add('water')
        self.add('juice', day=2, accepted=False)
        self.assertEqual(self.lookup()['status'], 'uncertain')
        self.add('tea', day=3)
        self.assertEqual(self.lookup()['value'], 'tea')

    def test_other_subject_and_private_rejection_cannot_change_public_answer(self):
        self.add('water')
        self.add('juice', subject='b', day=2, accepted=False)
        self.add('private', day=3, audience=('a',), accepted=False)
        self.assertEqual(self.lookup(audience=('a', 'b'))['value'], 'water')
        self.assertEqual(self.lookup()['status'], 'uncertain')

    def test_pending_eligible_scope_blocks_read_but_private_pending_does_not(self):
        self.add('water')
        self.add('private', day=2, audience=('a',), pending=True)
        self.assertEqual(self.lookup()['status'], 'pending')
        self.assertEqual(self.lookup(audience=('a', 'b'))['value'], 'water')

    def test_future_tombstoned_and_changed_source_binding(self):
        self.add('water')
        self.add('tea', day=3)
        self.assertEqual(self.lookup(as_of='2026-01-02T12:00:00Z')['value'], 'water')
        self.assertEqual(self.lookup(deleted_source_ids=['s1'])['value'], 'water')
        self.sources[1]['text'] = 'I no longer prefer tea.'
        self.assertEqual(self.lookup()['status'], 'pending')

    def test_changed_claim_cannot_reuse_valid_admission(self):
        self.add('water')
        self.rows[0]['proposals'][0]['value'] = 'tea'
        self.assertEqual(self.lookup()['status'], 'pending')

    def test_private_activity_names_never_enter_public_pattern_enumeration(self):
        self.add('secret activity', kind='choice', slot='activity', audience=('a',))
        q = {**self.query, 'operation': 'interests', 'slot': 'activity'}
        result = self.lookup(query=q, audience=('a', 'b'))
        self.assertEqual(result['patterns'], [])
        self.assertNotIn('secret activity', str(result))

    def test_same_session_counts_once_and_withdrawal_overrides_choices(self):
        for day in range(1, 4):
            self.add('origami', kind='choice', slot='activity', day=day, session='same')
        q = {**self.query, 'operation': 'interests', 'slot': 'activity'}
        self.assertEqual(self.lookup(query=q)['patterns'][0]['session_count'], 1)
        self.add('origami', kind='withdraw', slot='activity', day=4)
        self.assertEqual(self.lookup(query=q)['patterns'][0]['status'], 'withdrawn')

    def test_rejected_extra_choice_does_not_negate_verified_pattern(self):
        for day in range(1, 4):
            self.add('origami', kind='choice', slot='activity', day=day)
        self.add('origami', kind='choice', slot='activity', day=4, accepted=False)
        q = {**self.query, 'operation': 'interests', 'slot': 'activity'}
        self.assertEqual(self.lookup(query=q)['patterns'][0]['status'], 'tentative')
        self.add('origami', kind='withdraw', slot='activity', day=5, accepted=False)
        self.assertEqual(self.lookup(query=q)['status'], 'uncertain')

    def test_unknown_identity_and_injected_request_authority(self):
        self.add('water')
        self.assertEqual(self.lookup(query={**self.query, 'subject_id': 'unknown'})['status'], 'unknown_identity')
        with self.assertRaises(ValueError):
            self.lookup(query={**self.query, 'audience': ['a']})

    def test_event_keeps_original_quote_time_and_subject_scope(self):
        self.add('won science fair', kind='event', slot='achievement', day=2)
        self.add('built a boat', subject='b', kind='event', slot='activity', day=3)
        q = {**self.query, 'operation': 'events', 'slot': 'event'}
        result = self.lookup(query=q)
        self.assertEqual(len(result['events']), 1)
        event = result['events'][0]
        self.assertEqual(event['quote'], self.sources[0]['text'])
        self.assertEqual(event['reported_at'], self.sources[0]['at'])
        self.assertEqual(event['speaker_id'], 'a')

    def test_snapshot_copies_inputs_and_revision_changes_with_tombstone(self):
        self.add('water')
        snapshot = self.snapshot()
        deleted = self.snapshot(deleted_source_ids=['s0'])
        self.sources[0]['text'] = 'Changed after snapshot'
        self.assertEqual(snapshot.lookup(self.query, audience=['a'], as_of='2026-02-01T00:00:00Z')['value'], 'water')
        self.assertNotEqual(snapshot.revision, deleted.revision)


if __name__ == '__main__':
    unittest.main()
