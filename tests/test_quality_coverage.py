import copy
import unittest
from experiments.memory.quality_coverage import summarize,FIELDS


def fixture():
    corpus={'questions':[{'id':str(i),'category':'factual' if i<2 else 'pattern','text':'Independent question'+str(i)} for i in range(5)]}
    queries=[{'question':copy.deepcopy(q),'answer':{'text':'Explicit answer'}} for q in corpus['questions']]
    labels={q['id']:{**{k:k in ('task_correct','all_claims_grounded') for k in FIELDS},'rationale':'Explicit fictional control'} for q in corpus['questions']}
    return corpus,queries,labels


class QualityCoverageTests(unittest.TestCase):
    def test_direct_fact_perfection_does_not_hide_hard_case_failure(self):
        c,q,l=fixture()
        for i in ['2','3','4']:l[i]['all_claims_grounded']=False
        r=summarize(c,q,l);self.assertEqual(r['legacy_direct_fact_subset']['rate'],1)
        self.assertEqual(r['all_question_task_and_grounding']['rate'],.4);self.assertFalse(r['full_E5_accepted'])

    def test_missing_review_keeps_fixed_denominator_and_rate_pending(self):
        c,q,l=fixture();del l['4'];r=summarize(c,q,l)
        self.assertFalse(r['complete']);self.assertEqual(r['all_question_task_and_grounding']['expected'],5)
        self.assertIsNone(r['all_question_task_and_grounding']['rate']);self.assertIn({'id':'4','reason':'missing_review'},r['failures'])

    def test_missing_answer_not_silently_dropped(self):
        c,q,l=fixture();q.pop();del l['4'];r=summarize(c,q,l)
        self.assertEqual(r['expected'],5);self.assertEqual(r['collected'],4);self.assertIn({'id':'4','reason':'missing_answer'},r['failures'])

    def test_duplicate_changed_unknown_question_and_orphan_labels_rejected(self):
        c,q,l=fixture()
        with self.assertRaises(ValueError):summarize(c,q+[q[0]],l)
        altered=copy.deepcopy(q);altered[0]['question']['text']='A different question'
        with self.assertRaises(ValueError):summarize(c,altered,l)
        with self.assertRaises(ValueError):summarize(c,q[:-1],l)
        with self.assertRaises(ValueError):summarize(c,q,{**l,'unknown':l['0']})

    def test_implicit_truthy_or_unexplained_labels_are_not_reviewed(self):
        c,q,l=fixture()
        for key,value in [('task_correct',1),('rationale',''),('identity_error',None)]:
            bad=copy.deepcopy(l);bad['0'][key]=value
            with self.assertRaises(ValueError):summarize(c,q,bad)

    def test_empty_answer_not_credited_and_remains_expected(self):
        c,q,l=fixture();q[0]['answer']['text']=''
        with self.assertRaises(ValueError):summarize(c,q,l)
        l['0']['task_correct']=False;l['0']['all_claims_grounded']=False
        r=summarize(c,q,l);self.assertEqual(r['all_question_task_and_grounding']['correct'],4);self.assertEqual(r['expected'],5)

    def test_failure_flags_visible_even_if_task_label_is_true(self):
        c,q,l=fixture();l['0']['identity_error']=True;r=summarize(c,q,l)
        self.assertEqual(r['per_category']['factual']['identity_error'],1);self.assertFalse(r['full_E5_accepted'])
