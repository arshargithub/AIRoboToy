import base64
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

from tavi.saved_tests import save_test


class SavedTestTests(unittest.TestCase):
    def report(self):
        return {'schema_version':1,'kind':'paprika_controlled_conversation_diagnostics',
            'local_save_consent':{'destination':'project_private_local','explicit_save':True},
            'runs':[{'ended_at':'2026-11-02T00:00:00Z','local_audio_recording':{'enabled':False}}],
            'audio_included':False,'transcripts_included':False}

    def test_explicit_save_is_private_atomic_and_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'results';raw=json.dumps(self.report()).encode()
            result=save_test(raw,root);again=save_test(raw,root)
            self.assertEqual(result,again);self.assertEqual(len(list(root.glob('*.json'))),1)
            path=root/result['filename'];self.assertEqual(path.read_bytes(),raw)
            self.assertEqual(os.stat(path).st_mode&0o777,0o600)
            self.assertEqual(list(root.glob('.pending-*')),[])

    def test_audio_requires_closed_opted_in_bounded_recording(self):
        report=self.report();report.update(audio_included=True,transcripts_included=True)
        report['runs'][0]['local_audio']={'sample_rate':16000,'format':'mono_pcm16le_base64','closed':True,'sample_count':512,'pcm_base64':base64.b64encode(bytes(1024)).decode()}
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):save_test(json.dumps(report).encode(),Path(folder))
            report['runs'][0]['local_audio_recording']['enabled']=True
            self.assertTrue(save_test(json.dumps(report).encode(),Path(folder))['audio_included'])
            report['runs'][0]['local_audio']['closed']=False
            with self.assertRaises(ValueError):save_test(json.dumps(report).encode(),Path(folder))

    def test_unsaved_active_and_timings_only_privacy_bounds(self):
        with tempfile.TemporaryDirectory() as folder:
            for mutate in [lambda r:r.pop('local_save_consent'),lambda r:r['runs'][0].pop('ended_at'),lambda r:r.update(accepted_text=[{'request':'must not save'}])]:
                report=copy.deepcopy(self.report());mutate(report)
                with self.assertRaises(ValueError):save_test(json.dumps(report).encode(),Path(folder))
            self.assertEqual(list(Path(folder).iterdir()),[])
