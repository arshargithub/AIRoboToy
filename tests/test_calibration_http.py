import json,tempfile,unittest
from pathlib import Path
from tavi.mac_service import handler
from tavi.voice_calibration import VoiceCalibration,CONSENT
from tests import test_mac_service as mac_tests
from tests.test_voice_calibration import Catalog,Encoder
from tavi.speaker_profile import ROOT

class CalibrationHTTPTests(unittest.TestCase):
    request=mac_tests.MacServiceTests.request
    cleanup=mac_tests.MacServiceTests.cleanup
    def setUp(self):
        mac_tests.MacServiceTests.setUp(self)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.model=json.loads((ROOT/'experiments/speaker-id/model-manifest.json').read_text())['sha256'];self.encoder=Encoder(self.model);self.root=Path(self.tmp.name)/'calibration'
        self.cal=VoiceCalibration(Catalog(self.model),self.encoder,root=self.root,guard=lambda:None)
        base=self.server.RequestHandlerClass.__mro__[1]
        self.server.RequestHandlerClass=handler(base,self.loop,self.store,self.server.server_port,'a'*64,'b'*32,readiness=lambda:self.ready,calibration=self.cal)
        self.body={'person_id':'adultone','phase':'development','consent':CONSENT,'adult':True,'subject_willing':True,'alone':True,'local_only':True,'retain_audio':False,'own_voice':True}
    def test_public_page_and_private_status_have_no_vectors_or_credentials(self):
        self.assertEqual(self.request('/family-voices',auth=False)[0],200)
        self.assertEqual(self.request('/api/voices/status',auth=False)[0],403)
        status,raw=self.request('/api/voices/status');self.assertEqual(status,200);self.assertNotIn(b'embedding',raw);self.assertNotIn(b'token',raw)
    def test_invalid_or_missing_consent_never_dispatches_encoder_or_creates_visit(self):
        for b in ({},[],{**self.body,'adult':False},{**self.body,'local_only':False},{**self.body,'retain_audio':None}):self.assertEqual(self.request('/api/voices/begin',b)[0],400)
        self.assertFalse(self.root.exists());self.assertEqual(self.encoder.calls,0)
    def test_cross_origin_and_wrong_host_rejected_before_calibration(self):
        self.assertEqual(self.request('/api/voices/begin',self.body,origin='https://outside.example')[0],403)
        self.assertEqual(self.request('/api/voices/begin',self.body,host='outside.example')[0],403)
        self.assertFalse(self.root.exists())
    def test_candidate_check_does_not_qualify_or_learn_without_coverage(self):
        status,raw=self.request('/api/voices/begin',self.body);self.assertEqual(status,200);self.assertFalse(json.loads(raw)['recognition_enabled'])
        self.assertEqual(self.request('/api/voices/qualify',{})[0],200);self.assertFalse((self.root.parent/'identity-policy.json').exists());self.assertEqual(self.encoder.calls,0)
