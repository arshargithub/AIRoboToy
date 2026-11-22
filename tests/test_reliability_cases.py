import copy
import json
import unittest
from experiments.memory.build_reliability_cases import build,validate,public_question
from experiments.memory.guarded_worker import source_rejection
from experiments.memory.quality_coverage import summarize,FIELDS
from tavi.listen_only import listen_only


class ReliabilityCasesTests(unittest.TestCase):
    def test_shape_and_coverage(self):
        data,gold=build();r=validate(data,gold)
        self.assertEqual(r['episodes'],28);self.assertEqual(r['cases'],24)
        for category in ['correction','reporting','audience','comfort','pattern']:self.assertEqual(r['categories'][category],4)
        self.assertEqual(len(data['people']),4)

    def test_public_request_has_no_evaluator_fields(self):
        data,gold=build()
        for case in data['cases']:
            public=public_question({**case,'oracle':'DO_NOT_SEND','expected':'DO_NOT_SEND','support_ids':['DO_NOT_SEND']})
            self.assertNotIn('DO_NOT_SEND',json.dumps(public));self.assertNotIn('category',public);self.assertNotIn('after',public)
            self.assertEqual(set(public),{'id','text','asker','audience_ids','at','catalogue'})

    def test_unknown_source_is_quarantined_and_labelled_listen_uses_existing_local_route(self):
        data,gold=build();unknown=[s for s in data['episodes'] if s['speaker_id']=='unknown']
        self.assertEqual(len(unknown),1);self.assertEqual(source_rejection(unknown[0],data['people']),'unknown_speaker')
        local=[q for q in data['cases'] if gold['cases'][q['id']].get('route')=='local_listen_only']
        self.assertEqual(len(local),1);self.assertTrue(listen_only(local[0]['text']))

    def test_positive_oracle_cannot_use_future_or_private_support(self):
        data,gold=build()
        for sid in ['rel28','rel05']:
            bad=copy.deepcopy(gold);bad['cases']['rel-q01']['support_ids']=[sid]
            with self.assertRaises(ValueError):validate(data,bad)
        bad=copy.deepcopy(data);bad['episodes'][0]['at']='2099-01-01T00:00:00Z'
        with self.assertRaises(ValueError):validate(bad,gold)

    def test_private_canary_must_not_also_be_public(self):
        data,gold=build();bad=copy.deepcopy(data);bad['episodes'][11]['text']+=' COPPER-FERN-762'
        with self.assertRaises(ValueError):validate(bad,gold)

    def test_session_count_and_subject_are_not_interchangeable_with_source_count(self):
        data,gold=build();sources={s['id']:s for s in data['episodes']}
        same=gold['cases']['rel-q18']['support_ids'];self.assertEqual(len(same),3)
        self.assertEqual(len({sources[s]['session'] for s in same}),1)
        bad=copy.deepcopy(data)
        for e in bad['episodes']:
            if e['id'] in ['rel13','rel14','rel15']:e['session']='same'
        with self.assertRaises(ValueError):validate(bad,gold)

    def test_all24_are_in_score_and_missing_answer_stays_pending(self):
        data,gold=build();labels={q['id']:{**dict.fromkeys(FIELDS,False),'task_correct':True,'all_claims_grounded':True,'rationale':'Synthetic metric control'} for q in data['cases']}
        queries=[{'question':q,'answer':{'text':'Synthetic controlled answer'}} for q in data['cases']]
        report=summarize({'questions':data['cases']},queries,labels)
        self.assertEqual(report['all_question_task_and_grounding']['expected'],24);self.assertEqual(report['legacy_direct_fact_subset']['expected'],4)
        queries.pop();labels.pop('rel-q24');report=summarize({'questions':data['cases']},queries,labels)
        self.assertEqual(report['expected'],24);self.assertIsNone(report['all_question_task_and_grounding']['rate'])
