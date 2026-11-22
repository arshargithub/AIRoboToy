import copy
import unittest
from tavi.voice_continuity_review import validate


class ContinuityReviewTests(unittest.TestCase):
    def test_complete_samples_and_rating_or_written_feedback_required(self):
        data={'examples':[{'id':'x','variants':[{'id':'a'},{'id':'b'}]}]}
        body={'id':'a'*36,'manifest_sha256':'sha','completed':['x:a','x:b'],
              'reviews':{'x':{'rating':None,'notes':'The end has an odd pause.'}}}
        validate(body,data,'sha')
        for change in [{'completed':['x:a']},{'manifest_sha256':'old'}, {'reviews':{'x':{'rating':None,'notes':'   '}}}]:
            with self.assertRaises(ValueError):validate({**body,**change},data,'sha')
        body['reviews']['x']={'rating':'both_good','notes':''};validate(body,data,'sha')

    def test_pace_ratings_and_explicit_decision_are_distinct(self):
        data={'review_type':'pace','examples':[{'id':'x','variants':[{'id':'replay'}]}, {'id':'choice','decision':True,'variants':[]}]}
        body={'id':'a'*36,'manifest_sha256':'sha','completed':['x:replay'],
              'reviews':{'x':{'rating':'borderline','notes':''},'choice':{'rating':'timing_first','notes':''}}}
        validate(body,data,'sha')
        for key,value in [('x','pilot_with_limits'),('choice','acceptable'),('x','both_good')]:
            bad=copy.deepcopy(body);bad['reviews'][key]['rating']=value
            with self.assertRaises(ValueError):validate(bad,data,'sha')
        bad=copy.deepcopy(body);bad['completed']=[]
        with self.assertRaises(ValueError):validate(bad,data,'sha')
        body['reviews']['choice']={'rating':None,'notes':'I want to discuss this.'};validate(body,data,'sha')
