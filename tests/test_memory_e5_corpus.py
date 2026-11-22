import copy
import unittest
from experiments.memory.build_e5_corpus import build,validate

class CorpusTests(unittest.TestCase):
    def test_original_sample_sizes_and_timeline_are_preserved(self):
        value=validate(build())
        self.assertEqual((value['episodes'],value['questions'],value['patterns'],value['corrections']), (120,80,20,20))
        self.assertGreaterEqual(value['attribution_audience_traps'],20)

    def test_future_sources_and_hidden_support_cannot_satisfy_oracle(self):
        corpus=build();q=corpus['questions'][0]
        corpus['oracle'][q['id']]['source_ids']=['e120']
        with self.assertRaisesRegex(AssertionError,'Future'):validate(corpus)
        corpus=build();q=next(q for q in corpus['questions'] if q['category']=='audience_trap')
        oracle=corpus['oracle'][q['id']];oracle['source_ids']=oracle['hidden_source_ids']
        with self.assertRaisesRegex(AssertionError,'Hidden'):validate(corpus)

    def test_pattern_rubric_has_repetition_and_explicit_withdrawal_controls(self):
        corpus=build();by_id={e['id']:e for e in corpus['episodes']}
        labels=[corpus['oracle'][q['id']] for q in corpus['questions'] if q['category']=='pattern']
        self.assertEqual(sum(l.get('explicit_withdrawal',False) for l in labels),1)
        self.assertTrue(any(len(l['source_ids'])>=2 and len({by_id[s]['session'] for s in l['source_ids']})==1 for l in labels))

if __name__=='__main__':unittest.main()
