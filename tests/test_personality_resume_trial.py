import copy
import unittest
from experiments.memory.personality_resume_trial import combine_observations


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.cases=[{'id':'x'}]
        self.done={'case_id':'x','arm':'baseline','reply':{'status':'completed','usage_settled':True},'effective_request':{'instructions':'old'}}
        self.parent={'rows':[self.done,{'case_id':'x','arm':'candidate'}],'errors':['credit_balance_exhausted']}
        self.resumed={'rows':[{**copy.deepcopy(self.done),'arm':'candidate'}],'errors':[],
                      'additional_api_usd':.01,'full_comparison_additional_api_usd':.02,'total_spent_reserved_usd':1}
    def test_complete_matrix_keeps_interruption_and_segment_provenance(self):
        merged=combine_observations(self.parent,self.resumed,self.cases)
        self.assertEqual(len(merged['rows']),2)
        self.assertEqual(merged['recovered_parent_errors'],['credit_balance_exhausted'])
        self.assertEqual(merged['errors'],[])
        self.assertEqual([r['collection_segment'] for r in merged['rows']],['before_credit_restoration','after_credit_restoration'])
        self.assertNotIn('collection_segment',self.done)
    def test_missing_or_duplicate_response_cannot_become_complete(self):
        for rows in [[],[copy.deepcopy(self.done)]]:
            r={**self.resumed,'rows':rows}
            with self.assertRaises(ValueError):combine_observations(self.parent,r,self.cases)
