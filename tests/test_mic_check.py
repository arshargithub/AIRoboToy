import base64
import json
from pathlib import Path
import tempfile
import unittest
from tavi.mic_check import analyze


class MicCheckTests(unittest.TestCase):
    def test_partial_check_preserves_ratings_and_does_not_trust_requested_settings(self):
        data={'schema_version':1,'kind':'paprika_private_microphone_check','protocol_id':'microphone-quality-v1',
              'sample_rate':16000,'format':'mono_pcm16le_base64','complete':False,
              'rounds':[{'profile':'current','requested':{'echoCancellation':True,'noiseSuppression':True,'autoGainControl':False},'reported':{'echoCancellation':True}}],
              'clips':[{'number':1,'round':1,'profile':'current','position':'first','quality_rating':'impaired',
                        'capture_start_frame':0,'cue_context_frame':64*512,'sample_count':250*512,
                        'pcm_base64':base64.b64encode(bytes(250*1024)).decode()}]}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'fixture.json';path.write_text(json.dumps(data))
            result=analyze(path)
            self.assertFalse(result['complete']);self.assertFalse(result['clips'][0]['settings_verified'])
            self.assertEqual(result['clips'][0]['human_quality_rating'],'impaired')
            self.assertIsNone(result['clips'][0]['rms_dbfs'])
            self.assertNotIn('pcm_base64',json.dumps(result))
            data['complete']=True;path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'completion'):analyze(path)


if __name__=='__main__':unittest.main()
