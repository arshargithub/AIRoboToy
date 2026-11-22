import unittest

from experiments.memory.claim_admission import EXTRACT, VERIFY
from experiments.memory.claim_admission_temporal import TemporalAdmissionPipeline, TEMPORAL


class TemporalAdmissionTests(unittest.TestCase):
    def test_only_verification_instructions_change(self):
        calls = []
        pipeline = TemporalAdmissionPipeline({}, lambda instruction, payload: calls.append((instruction, payload)))
        payload = {'source': {'text': 'Fictional test'}}
        pipeline.request(EXTRACT, payload)
        pipeline.request(VERIFY, payload)
        self.assertEqual(calls, [(EXTRACT, payload), (VERIFY + TEMPORAL, payload)])


if __name__ == '__main__':
    unittest.main()
