import base64,importlib.util,json,tempfile,unittest
from pathlib import Path

@unittest.skipUnless(importlib.util.find_spec('numpy'),'Optional audio dependency not installed')
class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name)/'samples.json'
        self.data={'kind':'tavi_private_wake_samples','schema_version':1,'sample_rate':16000,'format':'mono_pcm16le_base64','complete':False,'clips':[{'number':1,'label':'positive','phrase':'TAH-vee','sample_count':16000,'pcm_base64':base64.b64encode(bytes(32000)).decode()}]}
    def load(self):
        from tavi.wake_samples import load_samples
        self.path.write_text(json.dumps(self.data));return load_samples(self.path)
    def test_pcm_is_decoded_without_changing_source(self):
        _,clips=self.load();before=self.path.read_bytes();self.assertEqual(clips[0]['pcm'].shape,(16000,));self.assertEqual(self.path.read_bytes(),before)
    def test_sample_rate_or_sample_count_mismatch_is_rejected(self):
        self.data['sample_rate']=48000
        with self.assertRaises(ValueError):self.load()
        self.data['sample_rate']=16000;self.data['clips'][0]['sample_count']=100
        with self.assertRaises(ValueError):self.load()
    def test_malformed_or_oversized_pcm_is_rejected(self):
        self.data['clips'][0]['pcm_base64']='not base64'
        with self.assertRaises(ValueError):self.load()
        self.data['clips'][0]['pcm_base64']=base64.b64encode(bytes(140000)).decode()
        with self.assertRaises(ValueError):self.load()
    def test_incomplete_session_cannot_claim_completion(self):
        self.data['complete']=True
        with self.assertRaises(ValueError):self.load()
