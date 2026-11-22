import unittest
from tavi.analyze_mlx_asr import covered_seconds


class CoverageTests(unittest.TestCase):
    def test_inflight_coverage_is_clipped_and_overlaps_are_not_counted_twice(self):
        self.assertEqual(covered_seconds(10,20,[(0,12),(11,16),(18,25)]),8)
        self.assertEqual(covered_seconds(10,20,[(0,9),(21,30)]),0)
        self.assertEqual(covered_seconds(10,20,[(0,30),(10,20)]),10)


if __name__=='__main__':unittest.main()
