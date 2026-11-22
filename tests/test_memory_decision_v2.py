import copy
import unittest
from experiments.memory.decision_contract_v2 import snapshot,validate

class RepairedDecisionTests(unittest.TestCase):
    def setUp(self):
        self.task={'actual_speaker_id':'a','people':{'a':'Sol','b':'Luka'},'audience_ids':['a','b'],'catalogue':[{'id':'book'}],'question':'Gift for Luka?'}
        self.evidence={'source_headers':{'s':{'speaker_id':'b'}},'facts':[{'text':'Luka likes funny stories.','sources':['s']}]}
        self.value={'memory_uses':[{'fact_index':0,'subject_id':'b'}],'catalogue_choices':[{'item_id':'book','disposition':'recommend','for_person_id':'b','fact_indices':[0]}],'text':'This could suit Luka.'}
    def check(self,v=None,**kw):
        h=snapshot(self.task,self.evidence)
        return validate(v or self.value,self.task,self.evidence,issued_snapshot=h,current_snapshot=kw.get('current',h))
    def test_gift_subject_can_differ_from_asker(self):self.assertTrue(self.check()['structural_check_passed'])
    def test_listening_can_use_memory_without_activity_choice(self):
        self.assertTrue(self.check({**self.value,'catalogue_choices':[],'text':'I can listen.'})['structural_check_passed'])
    def test_generic_unknown_person_advice_needs_no_personal_memory(self):
        v={'memory_uses':[],'catalogue_choices':[{'item_id':'book','disposition':'recommend','for_person_id':None,'fact_indices':[]}],'text':'A generic idea.'}
        self.assertTrue(self.check(v)['structural_check_passed'])
        v['catalogue_choices'][0]['fact_indices']=[0]
        with self.assertRaises(ValueError):self.check(v)
    def test_open_ended_suggestion_does_not_need_fake_catalogue_id(self):
        self.task['catalogue']=[]
        self.assertTrue(self.check({**self.value,'catalogue_choices':[]})['structural_check_passed'])
        with self.assertRaises(ValueError):self.check()
    def test_stale_context_unknown_source_or_invalid_reference_still_blocked(self):
        with self.assertRaises(ValueError):self.check(current='old')
        v=copy.deepcopy(self.value);v['memory_uses'][0]['fact_index']=99
        with self.assertRaises(ValueError):self.check(v)
        self.evidence['source_headers']['s']['speaker_id']='unknown'
        with self.assertRaises(ValueError):self.check()
    def test_conflicting_item_same_person_blocked_but_different_people_can_differ(self):
        v=copy.deepcopy(self.value);v['catalogue_choices'].append({**v['catalogue_choices'][0],'disposition':'exclude'})
        with self.assertRaises(ValueError):self.check(v)
        v['catalogue_choices'][1]['for_person_id']='a';v['catalogue_choices'][1]['fact_indices']=[]
        self.assertFalse(self.check(v)['semantic_grounding_verified'])
