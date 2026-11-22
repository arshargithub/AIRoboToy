from dataclasses import replace
import unittest

from experiments.memory.claim_admission import AdmissionPipeline
from experiments.memory.subject_contract import Claim, admission_digest


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.source = {'id': 's1', 'speaker_id': 'a', 'text': 'I prefer water.',
                       'session': 'one', 'at': '2026-01-01T00:00:00Z', 'audience_ids': ['a']}
        self.people = {'a': 'Ari', 'b': 'Bo'}
        self.claim = Claim('s1:0', 's1', 'a', 'drink', 'water', 'preference', 'self', self.source['text'])
        self.requests = []

    def pipeline(self, response):
        def request(instructions, payload):
            self.requests.append(payload)
            return response
        return AdmissionPipeline({}, request)

    def decision(self, **overrides):
        return {'decisions': [{'id': self.claim.id, 'entailed': True,
                               'reason': 'Full source asserts this.', **overrides}]}

    def test_success_binds_exact_claim_source_without_extra_context(self):
        result = self.pipeline(self.decision()).validate(self.source, self.people, [self.claim])
        self.assertEqual(result['admissions'], {self.claim.id: admission_digest(self.claim, self.source)})
        self.assertEqual(set(self.requests[0]), {'people', 'source', 'proposals'})

    def test_false_decision_never_admits(self):
        result = self.pipeline(self.decision(entailed=False)).validate(self.source, self.people, [self.claim])
        self.assertEqual(result['admissions'], {})

    def test_missing_duplicate_extra_or_nonboolean_decision_quarantines(self):
        for response in [{'decisions': []}, self.decision(id='other'),
                         self.decision(entailed='true'),
                         {'decisions': self.decision()['decisions'] * 2}]:
            with self.subTest(response=response), self.assertRaises(ValueError):
                self.pipeline(response).validate(self.source, self.people, [self.claim])

    def test_partial_acceptance_is_not_published_if_another_decision_missing(self):
        with self.assertRaises(ValueError):
            self.pipeline(self.decision()).validate(self.source, self.people,
                                                   [self.claim, replace(self.claim, id='s1:1')])

    def test_wrong_source_speaker_unknown_and_quote_rejected_before_model(self):
        for bad in [replace(self.claim, source_id='other'),
                    replace(self.claim, subject_id='b'),
                    replace(self.claim, subject_id='unknown'),
                    replace(self.claim, quote='I prefer juice.')]:
            self.assertEqual(self.pipeline({}).validate(self.source, self.people, [bad])['admissions'], {})
        self.source['speaker_id'] = 'unknown'
        reported = replace(self.claim, relation='reported')
        self.assertEqual(self.pipeline({}).validate(self.source, self.people, [reported])['admissions'], {})
        self.assertEqual(self.requests, [])

    def test_extractor_cannot_choose_source_id_or_self_authorize(self):
        row = {k: getattr(self.claim, k) for k in ('subject_id', 'slot', 'value', 'kind', 'relation', 'quote')}
        for extra in [{'source_id': 'other'}, {'accepted': True}, {'id': 'spoof'}]:
            with self.assertRaises(ValueError):
                self.pipeline({'claims': [{**row, **extra}]}).extract(self.source, self.people)
        self.assertEqual(self.pipeline({'claims': [row]}).extract(self.source, self.people), [self.claim])

    def test_duplicate_proposal_ids_rejected(self):
        with self.assertRaises(ValueError):
            self.pipeline({}).validate(self.source, self.people, [self.claim, self.claim])


if __name__ == '__main__':
    unittest.main()
