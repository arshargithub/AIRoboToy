import unittest
from experiments.memory.pause_candidate import prepare
from experiments.memory.prosody_measure import pcm
from tests.test_prosody_measure import wav


class PauseCandidateTests(unittest.TestCase):
    def test_only_internal_padding_changes_and_margins_remain(self):
        a=[0]*1200+[1000,-1000]*120+[0]*4800
        b=[0]*4800+[3000,-2000]*120+[0]*1200
        control,candidate,m=prepare([wav(a),wav(b)]);_,v=pcm(candidate)
        self.assertEqual(list(pcm(control)[1]),a+b)
        #200ms+200ms zero padding becomes100ms+100ms; outer50ms untouched.
        self.assertEqual(list(v),a[:-2400]+b[2400:]);self.assertEqual(m['joins'][0]['removed_ms'],200)
        self.assertTrue(m['only_zero_samples_removed']);self.assertTrue(m['outer_edges_untouched'])

    def test_quiet_nonzero_samples_never_trimmed(self):
        a=[1000]*120+[0]*1200+[1]*2400
        b=[-1]*2400+[0]*1200+[2000]*120
        control,candidate,m=prepare([wav(a),wav(b)])
        self.assertEqual(pcm(control)[1],pcm(candidate)[1]);self.assertEqual(m['joins'][0]['removed_ms'],0)

    def test_long_padding_reduction_capped_250ms(self):
        _,_,m=prepare([wav([1000]*120+[0]*24000),wav([0]*24000+[1000]*120)])
        self.assertEqual(m['joins'][0]['removed_ms'],250)

    def test_all_silent_clip_has_no_boundary_to_trim(self):
        a=wav([1000]*120+[0]*6000);b=wav([0]*6000)
        control,candidate,m=prepare([a,b]);self.assertEqual(control,candidate)
        self.assertIsNone(m['joins'][0]['original_exact_zero_ms'])

    def test_multiple_joins_preserve_middle_clip_and_order(self):
        a=wav([0]*4800+[777]*120+[0]*4800)
        _,candidate,m=prepare([a,a,a]);_,v=pcm(candidate)
        self.assertEqual(sum(x!=0 for x in v),360);self.assertEqual(len(m['joins']),2)
        self.assertEqual(len(v),3*9720-4*2400);self.assertTrue(m['nonzero_sequence_identical'])

    def test_no_padding_leaves_samples_identical(self):
        a=wav([1000,-2000]*120);b=wav([700,-800]*120)
        control,candidate,m=prepare([a,b]);self.assertEqual(control,candidate)

    def test_mismatched_rate_and_excessive_input_refused(self):
        for clips in [[wav([1]*120)], [wav([1]*120,16000),wav([1]*120)], [wav([1]*400000)]*2]:
            with self.assertRaises(ValueError):prepare(clips)

    def test_16k_preserves_duration_units(self):
        _,_,m=prepare([wav([10]*100+[0]*3200,16000),wav([0]*3200+[20]*100,16000)])
        self.assertEqual(m['joins'][0]['removed_ms'],200)
