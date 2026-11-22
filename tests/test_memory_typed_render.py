import unittest
from experiments.memory.typed_render import render_memory

class RenderTests(unittest.TestCase):
    def setUp(self):
        self.route={'status':'resolved','request':{'operation':'interests','subject_id':'p1','slot':'activity'}}
        self.people={'p1':'Cal','p2':'Vera'}

    def test_insufficient_and_withdrawn_cannot_become_positive_pattern(self):
        for state, phrase in [('insufficient_sessions',"isn't enough"),('withdrawn',"won't suggest")]:
            answer=render_memory(self.route,{'status':'evaluated','patterns':[{'activity':'drawing','status':state,'session_count':2,'source_ids':['s1']}]},'p1',self.people)
            self.assertIn(phrase,answer['text']);self.assertNotIn('might be an interest',answer['text'])

    def test_reported_event_retains_dated_source_and_exact_quote(self):
        self.route['request']['operation']='events'
        answer=render_memory(self.route,{'status':'supported','events':[{'speaker_id':'p2','quote':'Cal won yesterday.','reported_at':'2026-04-14T10:00:00Z','source_id':'s1'}]},'p1',self.people)
        self.assertEqual(answer['text'],'On April 14, 2026, Vera said: “Cal won yesterday.”')
        self.assertEqual(answer['source_ids'],['s1'])

    def test_unknown_and_invalid_status_fail_closed(self):
        answer=render_memory(self.route,{'status':'uncertain'},'p1',self.people)
        self.assertEqual(answer['source_ids'],[])
        with self.assertRaises(ValueError):
            render_memory(self.route,{'status':'evaluated','patterns':[{'activity':'drawing','status':'definitely'}]},'p1',self.people)
