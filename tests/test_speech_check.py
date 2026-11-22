import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from tavi.speech_check import PROTOCOL, calibration_row, crop_windows, load_collection, score


class SpeechCheckTests(unittest.TestCase):
    def test_delayed_onset_crop_keeps_every_segment_and_control(self):
        probabilities=[0]*40+[.99]*5+[0]*25+[.99]*4+[0]*25
        windows=crop_windows(probabilities,len(probabilities)*512)
        self.assertEqual(len(windows['current_100ms']),2)
        self.assertEqual(windows['current_100ms'][0]['start'],40*512-1600)
        self.assertEqual(windows['longer_1000ms'][0]['start'],40*512-16000)
        self.assertTrue(windows['current_100ms'][0]['endpoint_complete'])
        self.assertEqual(windows['full_clip'][0]['start'],0)
        self.assertEqual(crop_windows([0]*100,51200)['current_100ms'],[])

    def test_score_counts_lost_prefix_and_substitution_without_autocorrection(self):
        result=score('Wait, make it a space adventure instead.','A species adventure instead.')
        self.assertFalse(result['first_three_words']);self.assertFalse(result['exact_words'])
        self.assertEqual(result['word_edits'],4)
        self.assertEqual(score('Three keys.','three keys')['wer'],0)
        self.assertTrue(score('','An invented story')['silence_invented_words'])

    def test_word_scores_from_a_different_transcript_are_excluded_from_calibration(self):
        row={'number':1,'model':'tiny.en','crop':'full_clip','condition':'overlap','category':'request',
             'decode_ms':100,'windows':[{}],**score('space adventure','species adventure'),
             'segment_confidence_by_window':[{'segments':[{'avg_logprob':-.2,'no_speech_prob':.01,'compression_ratio':1.1}]}],
             'word_alignment_by_window':[{'primary_text_agrees':False,'alignment_ms':60,'words':[{'probability':.99}]}]}
        result=calibration_row(row,'source','protocol')
        self.assertIsNone(result['min_word_probability'])
        self.assertFalse(result['word_alignment_all_agree'])
        self.assertEqual(result['min_avg_logprob'],-.2)
        self.assertEqual(result['label_source'],'scripted_reference_unverified')

    def test_collection_requires_exact_pcm_protocol_and_contiguous_cue(self):
        raw=PROTOCOL.read_bytes();plan=json.loads(raw)
        clip={**plan['trials'][0],'capture_start_frame':2048,'cue_context_frame':2048+64*512,
              'sample_count':250*512,'pcm_base64':base64.b64encode(bytes(250*1024)).decode()}
        data={'schema_version':1,'kind':plan['kind'],'protocol_id':plan['protocol_id'],
              'protocol_sha256':hashlib.sha256(raw).hexdigest(),'sample_rate':16000,
              'format':'mono_pcm16le_base64','complete':False,'clips':[clip]}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'synthetic.json';path.write_text(json.dumps(data))
            self.assertEqual(len(load_collection(path)[2]),1)
            data['complete']=True;path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'eight'):load_collection(path)
            data['complete']=False;clip['cue_context_frame']+=1;path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'cue'):load_collection(path)


if __name__=='__main__':unittest.main()
