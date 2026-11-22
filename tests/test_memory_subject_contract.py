from dataclasses import replace
import unittest

from experiments.memory.subject_contract import Claim, admission_digest, preference, pattern


class SubjectContractTests(unittest.TestCase):
    def setUp(self):
        self.sources = []
        self.claims = []
        self.admitted = {}
        self.scope = dict(subject='a', slot='drink', audience=['a'],
                          as_of='2026-03-01T12:00:00Z')

    def add(self, person, value, *, day=1, kind='preference', session=None,
            audience=('a', 'b'), admit=True):
        sid = f'e{len(self.sources)}'
        text = f'I {kind} {value}.'
        self.sources.append(dict(id=sid, speaker_id=person, audience_ids=list(audience),
                                 text=text, session=session or sid,
                                 at=f'2026-02-{day:02}T12:00:00Z'))
        claim = Claim(sid, sid, person, 'drink', value, kind, 'self', text)
        self.claims.append(claim)
        if admit:
            self.admitted[sid] = admission_digest(claim, self.sources[-1])
        return claim

    def pref(self, **overrides):
        return preference(self.claims, self.sources, self.admitted,
                          **{**self.scope, **overrides})

    def pat(self, **overrides):
        return pattern(self.claims, self.sources, self.admitted, activity='tea',
                       **{**self.scope, **overrides})

    def test_other_person_newer_correction_cannot_change_subject(self):
        self.add('a', 'oat milk')
        self.add('b', 'mint tea')
        self.add('b', 'sparkling water', day=2)
        self.assertEqual(self.pref()['value'], 'oat milk')
        self.assertEqual(self.pref(subject='b')['value'], 'sparkling water')

    def test_native_wrong_self_assignment_cannot_override_canonical_speaker(self):
        claim = self.add('b', 'water')
        self.claims[0] = replace(claim, subject_id='a')
        self.admitted[claim.id] = admission_digest(self.claims[0], self.sources[0])
        self.assertEqual(self.pref()['status'], 'unknown')

    def test_unadmitted_or_unknown_speaker_stays_unknown(self):
        self.add('a', 'water', admit=False)
        unknown = self.add('unknown', 'tea')
        self.claims[1] = replace(unknown, subject_id='a', relation='reported')
        self.admitted[unknown.id] = admission_digest(self.claims[1], self.sources[1])
        self.assertEqual(self.pref()['status'], 'unknown')

    def test_admission_is_not_inferred_from_quote_presence(self):
        self.add('a', 'water', admit=False)
        self.assertEqual(self.pref()['status'], 'unknown')
        self.admitted['e0'] = admission_digest(self.claims[0], self.sources[0])
        self.assertEqual(self.pref()['value'], 'water')
        self.claims[0] = replace(self.claims[0], quote='Not present in original.')
        self.admitted['e0'] = admission_digest(self.claims[0], self.sources[0])
        self.assertEqual(self.pref()['status'], 'unknown')

    def test_audience_tombstone_and_time_remain_authoritative(self):
        self.add('a', 'private', audience=('a',))
        self.assertEqual(self.pref(audience=['a', 'b'])['status'], 'unknown')
        self.assertEqual(self.pref(deleted_source_ids=['e0'])['status'], 'unknown')
        self.assertEqual(self.pref(as_of='2026-01-01T00:00:00Z')['status'], 'unknown')

    def test_same_session_and_duplicate_claims_do_not_create_pattern(self):
        for day in range(1, 4):
            self.add('a', 'tea', kind='choice', day=day, session='one')
        self.claims += list(self.claims)
        result = self.pat()
        self.assertEqual(result['status'], 'insufficient_sessions')
        self.assertEqual(result['session_count'], 1)

    def test_three_distinct_sessions_are_tentative_and_delete_retracts(self):
        for day in range(1, 4):
            self.add('a', 'tea', kind='choice', day=day)
        self.assertEqual(self.pat()['status'], 'tentative')
        self.assertEqual(self.pat(deleted_source_ids=['e1'])['status'], 'insufficient_sessions')

    def test_withdrawal_blocks_even_later_choice_until_explicit_resumption(self):
        for day in range(1, 4):
            self.add('a', 'tea', kind='choice', day=day)
        self.add('a', 'tea', kind='withdraw', day=4)
        self.add('a', 'tea', kind='choice', day=5)
        self.assertEqual(self.pat()['status'], 'withdrawn')
        self.add('a', 'tea', kind='resume', day=6)
        self.assertEqual(self.pat()['status'], 'insufficient_sessions')
        for day in range(7, 10):
            self.add('a', 'tea', kind='choice', day=day)
        self.assertEqual(self.pat()['session_count'], 3)

    def test_conflicting_equal_time_preferences_abstain(self):
        self.add('a', 'water')
        self.add('a', 'tea')
        self.assertEqual(self.pref()['status'], 'conflict')

    def test_preference_withdrawal_does_not_resurrect_superseded_value(self):
        self.add('a', 'water')
        self.add('a', 'tea', day=2)
        self.add('a', 'tea', kind='withdraw', day=3)
        self.assertEqual(self.pref()['status'], 'withdrawn')
        self.add('a', 'juice', day=4)
        self.assertEqual(self.pref()['value'], 'juice')

    def test_contradictory_claim_id_quarantines_projection(self):
        c = self.add('a', 'water')
        self.claims.append(replace(c, value='tea'))
        with self.assertRaises(ValueError):
            self.pref()

    def test_changed_claim_or_source_cannot_reuse_old_admission(self):
        original = self.add('a', 'water')
        self.claims[0] = replace(original, value='tea')
        self.assertEqual(self.pref()['status'], 'unknown')
        self.claims[0] = original
        self.sources[0]['audience_ids'].append('c')
        self.assertEqual(self.pref()['status'], 'unknown')


if __name__ == '__main__':
    unittest.main()
