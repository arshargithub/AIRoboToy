import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


@unittest.skipUnless(importlib.util.find_spec('numpy'), 'Optional audio dependency not installed')
class NameComparisonTests(unittest.TestCase):
    def setUp(self):
        from tavi.name_comparison import protocol
        self.plan, self.digest = protocol()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'comparison.json'
        count = self.plan['minimum_frames'] * 512
        encoded = base64.b64encode(bytes(count * 2)).decode()
        self.data = {'schema_version': 1, 'kind': self.plan['kind'], 'protocol_id': self.plan['protocol_id'],
                     'protocol_sha256': self.digest, 'complete': True, 'sample_rate': 16000,
                     'format': 'mono_pcm16le_base64',
                     'clips': [{**t, 'sample_count': count, 'pcm_base64': encoded} for t in self.plan['trials']]}

    def load(self):
        from tavi.name_comparison import load_collection
        self.path.write_text(json.dumps(self.data))
        return load_collection(self.path)

    def test_frozen_collection_accepts_both_names_without_modifying_audio(self):
        _, clips = self.load()
        self.assertEqual(len(clips), 32)
        self.assertEqual(sum(c['target'] == 'paprika' for c in clips), 8)
        self.assertEqual(sum(c['target'] == 'tavi' for c in clips), 8)
        self.assertEqual(sum(c['category'] == 'name_alone' for c in clips), 8)
        self.assertEqual(sum(c['category'] == 'request' for c in clips), 8)
        before = self.path.read_bytes()
        from tavi.name_comparison import load_collection
        load_collection(self.path)
        self.assertEqual(before, self.path.read_bytes())

    def test_partial_or_changed_protocol_is_rejected(self):
        self.data['complete'] = False
        with self.assertRaises(ValueError): self.load()
        self.data['complete'] = True
        self.data['protocol_sha256'] = 'changed'
        with self.assertRaises(ValueError): self.load()

    def test_altered_labels_or_pcm_are_rejected(self):
        self.data['clips'][0]['target'] = 'paprika'
        with self.assertRaises(ValueError): self.load()
        self.data['clips'][0]['target'] = 'tavi'
        self.data['clips'][0]['sample_count'] = 1
        with self.assertRaises(ValueError): self.load()

    def test_matches_and_counts_keep_mentions_separate_from_confusables(self):
        from tavi.name_comparison import matches, summarize
        names = ['tavi', 'paprika']
        self.assertEqual(matches('Paprika, hello!', names), ['paprika'])
        self.assertEqual(matches('Octavian and paprikas', names), [])
        rows = [{**t, 'matches': matches(t['phrase'], names)} for t in self.plan['trials']]
        report = summarize(rows, names)
        for name in names:
            self.assertEqual(report['names'][name]['detected_calls'], 8)
            self.assertEqual(report['names'][name]['groups']['confusable'], {'clips': 12, 'name_matches': 0})
            self.assertEqual(report['names'][name]['groups']['mention'], {'clips': 4, 'name_matches': 2})
            self.assertEqual(report['names'][name]['groups']['other_name'], {'clips': 8, 'name_matches': 0})
        self.assertIsNone(report['median_decode_ms'])


if __name__ == '__main__':
    unittest.main()
