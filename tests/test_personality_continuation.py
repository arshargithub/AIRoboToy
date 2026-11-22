import unittest
from experiments.memory.personality_continuation import remaining_requests


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.cases=[{'id':'one'},{'id':'two'},{'id':'reg','arms':['candidate']}]
        self.done={'case_id':'one','arm':'baseline',
                   'reply':{'status':'completed','usage_settled':True},
                   'effective_request':{'instructions':'frozen'}}
    def test_complete_results_skipped_and_pre_inference_credit_failure_remains_pending(self):
        rows=[self.done,{'case_id':'one','arm':'candidate'}]
        self.assertEqual(remaining_requests(self.cases,rows),[
            {'case_id':'one','arm':'candidate'},{'case_id':'two','arm':'candidate'},
            {'case_id':'two','arm':'baseline'},{'case_id':'reg','arm':'candidate'}])
    def test_uncertain_sent_or_unsettled_completed_reply_cannot_be_repeated(self):
        for row in [{'case_id':'one','arm':'candidate','effective_request':{}},
                    {'case_id':'one','arm':'candidate','reservation':'unknown'},
                    {**self.done,'reply':{'status':'completed','usage_settled':False}}]:
            with self.assertRaises(ValueError):remaining_requests(self.cases,[row])
    def test_duplicate_or_foreign_record_is_rejected(self):
        for rows in [[self.done,self.done],[{'case_id':'foreign','arm':'candidate'}]]:
            with self.assertRaises(ValueError):remaining_requests(self.cases,rows)
