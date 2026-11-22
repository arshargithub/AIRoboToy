import unittest
from tavi.memory_pace_review import validate_review
class PaceFeedbackTests(unittest.TestCase):
    def test_incomplete_or_changed_preview_cannot_approve_goal(self):
        data={'examples':[{'id':'x'},{'id':'y'}],'waits_ms':[3000,5000]}
        b={'id':'a'*36,'manifest_sha256':'frozen','completed':['x:3000','x:5000','y:3000','y:5000'],'decision':'allow_five_for_memory','notes':'Only for thoughtful questions.'}
        self.assertTrue(validate_review(b,data,'frozen'))
        for bad in [dict(completed=b['completed'][:-1]),dict(manifest_sha256='old'),dict(decision='automatically_approved')]:
            with self.assertRaises(ValueError):validate_review({**b,**bad},data,'frozen')
