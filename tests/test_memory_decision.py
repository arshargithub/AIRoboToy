import copy
import unittest
from experiments.memory.decision_contract import snapshot,validate

class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.task={'actual_speaker_id':'a','people':{'a':'Sol','b':'Luka'},'audience_ids':['a','b'],
                   'catalogue':[{'id':'book','name':'Pebble Post'}],'question':'A gift for Luka?'}
        self.evidence={'source_headers':{'s':{'speaker_id':'a'}},
                       'facts':[{'text':'Sol finished Pebble Post.','sources':['s']}]}
        self.receipt={'recipient_id':'b','mode':'suggest','memory_uses':[],
                      'recommendations':[{'item_id':'book','fact_indices':[]}],'exclusions':[],'text':'It might suit Luka.'}
    def check(self,receipt=None,**kw):
        h=snapshot(self.task,self.evidence)
        return validate(receipt or self.receipt,self.task,self.evidence,
                        issued_snapshot=h,current_snapshot=kw.get('current',h))
    def test_stale_identity_audience_question_or_evidence_cannot_publish(self):
        for field,new in [('actual_speaker_id','b'),('audience_ids',['b']),('question','Other question')]:
            task=copy.deepcopy(self.task);task[field]=new
            with self.assertRaises(ValueError):self.check(current=snapshot(task,self.evidence))
        evidence=copy.deepcopy(self.evidence);evidence['facts'][0]['text']='Deleted or corrected'
        with self.assertRaises(ValueError):self.check(current=snapshot(self.task,evidence))
    def test_wrong_recipient_exclusion_and_contradictory_choice_rejected(self):
        r=copy.deepcopy(self.receipt);r['recommendations']=[]
        r['exclusions']=[{'item_id':'book','subject_id':'a','fact_indices':[0]}]
        with self.assertRaises(ValueError):self.check(r)
        r['exclusions'][0]['subject_id']='b';r['recommendations']=self.receipt['recommendations']
        with self.assertRaises(ValueError):self.check(r)
    def test_invalid_references_unknown_sources_and_hidden_advice_rejected(self):
        for change in [dict(memory_uses=[{'fact_index':99,'subject_id':'b'}]),
                       dict(recommendations=[{'item_id':'invented','fact_indices':[]}]),dict(mode='listen')]:
            with self.assertRaises(ValueError):self.check({**self.receipt,**change})
        self.evidence['source_headers']['s']['speaker_id']='unknown'
        with self.assertRaises(ValueError):self.check({**self.receipt,'memory_uses':[{'fact_index':0,'subject_id':'a'}]})
    def test_structural_pass_is_not_claimed_entailment(self):
        # A model can still misassign the subject of a valid reference. Preserve
        # that limitation explicitly; do not write a test claiming this is safe.
        r={**self.receipt,'memory_uses':[{'fact_index':0,'subject_id':'b'}]}
        value=self.check(r);self.assertTrue(value['structural_check_passed'])
        self.assertFalse(value['semantic_grounding_verified'])
