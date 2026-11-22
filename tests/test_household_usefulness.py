import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import unittest
from experiments.memory.household_usefulness_trial import validate_inputs,scope_for

class UsefulnessProtocolTests(unittest.TestCase):
    def setUp(self):self.data=json.loads(Path('experiments/memory/household-usefulness-input-v1.json').read_text())
    def test_denominator_and_real_session_pattern_controls(self):
        validate_inputs(self.data)
        self.assertEqual(len(self.data['sources']),16)
        self.assertEqual(len({s['session'] for s in self.data['sources'] if s['alias'] in self.data['cases'][0]['expected_support']}),3)
        for change in ('duplicate','future','pattern'):
            data=deepcopy(self.data)
            if change=='duplicate':data['sources'][1]['alias']=data['sources'][0]['alias']
            if change=='future':data['cases'][0]['expected_support'].append('drawing-break')
            if change=='pattern':data['sources'][4]['session']=data['sources'][2]['session']
            with self.assertRaises(ValueError):validate_inputs(data)
    def test_control_and_memory_arm_task_is_identical_and_rubric_free(self):
        bank=SimpleNamespace(generation=lambda:('fixture',0));c=next(c for c in self.data['cases'] if c['control'])
        a=scope_for(c,self.data,bank);b=scope_for({**c,'control':False,'required':'Hidden grading instruction','expected_support':['nope']},self.data,bank)
        self.assertEqual(a,b)
        self.assertNotIn('Hidden grading',json.dumps(a));self.assertNotIn('expected_support',json.dumps(a))
    def test_declared_cutoff_does_not_look_ahead_into_withdrawal(self):
        c=self.data['cases'][0];available=self.data['sources'][:c['after_sources']]
        self.assertNotIn('drawing-break',[s['alias'] for s in available])
        self.assertTrue(all(s['at']<=c['at'] for s in available))
    def test_unknown_querier_and_changed_control_denominator_rejected(self):
        for kind in ('identity','controls'):
            d=deepcopy(self.data)
            if kind=='identity':d['cases'][0]['speaker']='unknown'
            else:next(c for c in d['cases'] if c['control'])['control']=False
            with self.assertRaises(ValueError):validate_inputs(d)
