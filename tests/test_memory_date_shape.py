from datetime import datetime
import unittest
from experiments.memory.hindsight_compat import normalize_date_results

class DateShapeTests(unittest.TestCase):
    def test_both_supported_native_shapes_preserve_exact_match(self):
        date=datetime(2026,3,12)
        self.assertEqual(normalize_date_results([('March12',date,'day')]),[('March12',date)])
        self.assertEqual(normalize_date_results([('March12',date)]),[('March12',date)])
        self.assertIsNone(normalize_date_results(None))

    def test_invalid_native_shape_does_not_invent_a_date(self):
        for value in [[('today',)], [('today','2026-03-12')], [('today',datetime.now(),'day','extra')]]:
            with self.assertRaises(ValueError):normalize_date_results(value)

if __name__=='__main__':unittest.main()
