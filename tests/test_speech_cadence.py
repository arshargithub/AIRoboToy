from array import array
import unittest
from experiments.speech.cadence import write_pcm,read_pcm,edges,join,split

class CadenceTests(unittest.TestCase):
    def test_isolated_impulse_does_not_become_sustained_speech(self):
        a=array('h',[0]*2400+[8000]*240+[0]*2400)
        self.assertTrue(all(v['leading_ms'] is None for v in edges(write_pcm(a))['threshold_edges_ms'].values()))
    def test_threshold_sensitivity_preserves_quiet_phonemes_in_original(self):
        a=array('h',[0]*2400+[150]*2400+[5000]*4800+[0]*2400);wav=write_pcm(a)
        report=edges(wav)['threshold_edges_ms'];self.assertEqual(report['-50']['leading_ms'],100)
        self.assertEqual(report['-30']['leading_ms'],200);self.assertEqual(read_pcm(wav),a)
    def test_chunk_join_keeps_all_samples_and_text(self):
        text='A cardboard boat could float in a bowl. We can add a paper flag.'
        chunks=split(text);self.assertEqual(''.join(chunks),text);self.assertEqual(len(chunks),2)
        first=array('h',[1]*500);second=array('h',[-2]*600)
        self.assertEqual(read_pcm(join([write_pcm(first),write_pcm(second)])),first+second)
