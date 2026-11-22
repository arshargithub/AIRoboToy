from array import array
import unittest
from experiments.speech.cadence import read_pcm,write_pcm
from experiments.speech.pause_preview import shorten_join_zeros

class PausePreviewTests(unittest.TestCase):
    def test_only_join_edge_zeros_removed_and_body_interior_unchanged(self):
        body=array('h',[1,-1,0,0,0,2,-2]);a=array('h',[0]*6000)+body+array('h',[0]*6000)
        wav,edits=shorten_join_zeros([write_pcm(a),write_pcm(a)])
        self.assertEqual(read_pcm(wav),a[:-2880]+a[2880:])
        self.assertEqual(edits[0]['removed_leading_samples'],0);self.assertEqual(edits[1]['removed_trailing_samples'],0)
        self.assertTrue(all(e['removed_samples_were_zero'] for e in edits))
    def test_quiet_nonzero_samples_and_short_silence_cannot_be_trimmed(self):
        a=array('h',[0]*100+[1]*9000+[0]*120)
        wav,edits=shorten_join_zeros([write_pcm(a),write_pcm(a)])
        self.assertEqual(read_pcm(wav),a+a);self.assertTrue(all(e['removed_leading_samples']==e['removed_trailing_samples']==0 for e in edits))
    def test_single_chunk_is_unchanged_and_wholly_silent_input_rejected(self):
        a=array('h',[0]*9000+[2]*480+[0]*9000)
        wav,_=shorten_join_zeros([write_pcm(a)]);self.assertEqual(read_pcm(wav),a)
        with self.assertRaises(ValueError):shorten_join_zeros([write_pcm(array('h',[0]*500))])
