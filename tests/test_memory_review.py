import json
from pathlib import Path
import tempfile
import unittest
import uuid
from copy import deepcopy
from unittest.mock import patch
from tavi.memory_review import save_review, validate_review
from tavi.experiment_workflow import digest

class MemoryReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        manifest = Path(temporary.name) / 'examples.json'
        self.examples = {
            'scope': 'Fictional unit test',
            'source_run': 'synthetic',
            'observations_sha256': 'a' * 64,
            'examples': [{'id': 'one'}, {'id': 'two'}],
        }
        manifest.write_text(json.dumps(self.examples))
        self.enterContext(patch('tavi.memory_review.EXAMPLES', manifest))
        self.body = {'id': str(uuid.uuid4()), 'ratings': {}, 'notes': '', 'decision': None,
                     'examples_sha256': digest(manifest)}

    def test_partial_resume_and_final_are_local_distinct_revisions(self):
        with tempfile.TemporaryDirectory() as folder:
            self.body['ratings'][self.examples['examples'][0]['id']]='natural'
            self.assertFalse(save_review(self.body,self.examples,folder)['complete'])
            self.body['ratings']={r['id']:'stiff' for r in self.examples['examples']}
            self.body['decision']='warmer'
            result=save_review(self.body,self.examples,folder)
            self.assertTrue(result['complete'])
            self.assertEqual(result,save_review(self.body,self.examples,folder))
            self.assertEqual(len(list(Path(folder).glob('*.json'))),2)
            self.assertTrue(all(p.stat().st_mode & 0o077 == 0 for p in Path(folder).glob('*.json')))

    def test_incomplete_stale_and_invalid_feedback_cannot_finish(self):
        for mutation in [{'decision':'acceptable'},{'examples_sha256':'stale'},{'ratings':{'fake':'natural'}},{'id':'../../elsewhere'}]:
            with self.assertRaises(ValueError):validate_review({**self.body,**mutation},self.examples)

    def test_companion_selection_and_free_text_keep_original_review_compatible(self):
        examples={**self.examples,'review_kind':'companion'}
        self.body['comments']={e['id']:'This is warmer, but I would rather it listened.' for e in examples['examples']}
        self.body['decision']='warmer'
        self.assertTrue(validate_review(self.body,examples))
        self.body['ratings']={e['id']:'A' for e in examples['examples']}
        self.assertTrue(validate_review(self.body,examples))
        with self.assertRaises(ValueError):validate_review(self.body,self.examples)
        self.body['ratings']={e['id']:'none' for e in examples['examples']}
        self.assertTrue(validate_review(self.body,examples))
