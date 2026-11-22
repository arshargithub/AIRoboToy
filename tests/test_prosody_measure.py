from io import BytesIO
import array
import unittest
import wave
from experiments.memory.prosody_measure import analyze,join,compare


def wav(samples,rate=24000,channels=1):
    out=BytesIO()
    with wave.open(out,'wb') as f:
        f.setnchannels(channels);f.setsampwidth(2);f.setframerate(rate);f.writeframes(array.array('h',samples).tobytes())
    return out.getvalue()


class ProsodyMeasureTests(unittest.TestCase):
    def test_known_edges_and_join_without_transport_gap(self):
        #100ms leading +200ms trailing padding around100ms nonzero waveform.
        a=analyze(wav([0]*2400+[1000,-1000]*1200+[0]*4800))
        for t in a['thresholds'].values():
            self.assertEqual(t['leading_low_energy_ms'],100);self.assertEqual(t['trailing_low_energy_ms'],200)
        self.assertEqual(join(a,a)['thresholds']['-45']['low_energy_gap_ms'],300)

    def test_all_silent_is_missing_boundary_not_zero_gap(self):
        a=analyze(wav([0]*2400));self.assertTrue(a['thresholds']['-45']['all_low_energy'])
        self.assertIsNone(join(a,a)['thresholds']['-45']['low_energy_gap_ms'])

    def test_threshold_sensitivity_preserves_quiet_material(self):
        a=analyze(wav([120]*1200+[1000]*1200))
        self.assertEqual(a['thresholds']['-50']['leading_low_energy_ms'],0)
        self.assertEqual(a['thresholds']['-45']['leading_low_energy_ms'],50)

    def test_level_and_boundary_step_are_separate(self):
        a=analyze(wav([1000]*2400));b=analyze(wav([-2000]*2400));j=join(a,b)
        self.assertAlmostEqual(j['thresholds']['-45']['active_window_level_change_db'],6.0206,places=3)
        self.assertAlmostEqual(j['sample_step_full_scale'],3000/32768)

    def test_comparison_distinguishes_gain_from_waveform_and_alignment(self):
        a=wav([1000,-1000]*1200);b=wav([2000,-2000]*1200)
        c=compare(a,b);self.assertFalse(c['pcm_identical']);self.assertAlmostEqual(c['cosine'],1)
        self.assertEqual(c['least_squares_gain_b_over_a'],2);self.assertEqual(c['normalized_residual_after_gain'],0)
        self.assertTrue(compare(a,a)['pcm_identical']);self.assertFalse(compare(a,wav([1000]*1200))['same_rate_and_length'])

    def test_partial_last_window_counted(self):
        a=analyze(wav([0]*120+[1000]*17));self.assertEqual(a['frames'],137)
        self.assertEqual(a['thresholds']['-45']['leading_low_energy_ms'],5)
        self.assertAlmostEqual(a['thresholds']['-45']['active_window_ms'],17/24)

    def test_invalid_or_truncated_wav_refused(self):
        for raw in [wav([1000]*100,rate=8000),wav([1000]*100,channels=2),wav([1000]*100)[:-2],wav([])]:
            with self.assertRaises(ValueError):analyze(raw)
