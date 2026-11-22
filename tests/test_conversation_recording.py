import base64
import json
from pathlib import Path
import struct
import tempfile
import unittest
import wave
from tavi.conversation_recording import extract


class ConversationRecordingTests(unittest.TestCase):
    def test_exact_asr_audio_and_broader_context_match_confidence_and_human_review(self):
        raw=struct.pack('<'+'h'*2048,*range(2048))
        data={'schema_version':1,'kind':'paprika_controlled_conversation_diagnostics','runs':[
            {'asr_run_id':'run-a','local_audio_recording':{'enabled':True},
             'local_audio':{'sample_rate':16000,'format':'mono_pcm16le_base64','closed':True,
                            'sample_count':2048,'start_context_frame':16000,'end_context_frame':18048,
                            'first_sequence':0,'last_sequence':3,'pcm_base64':base64.b64encode(raw).decode()},
             'recognition_results':[{'recognition_id':'recognition-a','asr_run_id':'run-a',
                                     'audio_start_sample':512,'audio_samples':512,'confidence':{'min_avg_logprob':-.9}}]}],
            'accepted_text':[{'recognition_id':'recognition-a','request':'Scripted words'}],
            'reviews':[{'recognition_id':'recognition-a','rating':'correct'}]}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'input.json';path.write_text(json.dumps(data))
            _,manifest=extract(path,Path(folder)/'out');case=manifest['runs'][0]['recognitions'][0]
            with wave.open(case['asr_input_wav']) as audio:self.assertEqual(audio.readframes(512),raw[1024:2048])
            with wave.open(case['context_wav']) as audio:self.assertEqual(audio.readframes(2048),raw)
            self.assertEqual(case['human_recognition_reviews'][0]['rating'],'correct')
            self.assertEqual(case['confidence']['min_avg_logprob'],-.9)
            self.assertNotIn('pcm_base64',json.dumps(manifest))
            data['runs'][0]['recognition_results'][0]['audio_samples']=99999;path.write_text(json.dumps(data))
            _,manifest=extract(path,Path(folder)/'other')
            self.assertIn('slice_unavailable',manifest['runs'][0]['recognitions'][0])
            data['runs'][0]['local_audio_recording']['enabled']=False;path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'opt-in'):extract(path,Path(folder)/'bad')
