from copy import deepcopy
import unittest
from experiments.memory.access_evidence import with_access_decision
from experiments.memory.decision_contract import snapshot


def setup():
    task={'actual_speaker_id':'c','people':{'a':'Edda','c':'Bram'},'audience_ids':['c'],'conversation_at':'2026-03-29T10:00:00Z'}
    sources=[{'id':'s1','speaker_id':'c','session':'one','at':'2026-03-02T00:00:00Z','audience_ids':['c'],'text':'My private message is CANARY.'},
        {'id':'s2','speaker_id':'a','session':'two','at':'2026-03-03T00:00:00Z','audience_ids':['a','c'],'text':'Bram likes maps, according to him.'}]
    raw={'source_headers':{'untrusted':'ignored'},'app_access_decision':{'allow_everything':True},
        'facts':[{'text':'Bram private CANARY','sources':['s1'],'kind':'world'},{'text':'Bram likes maps','sources':['s2'],'kind':'world'}]}
    return task,raw,sources


class AccessEvidenceTests(unittest.TestCase):
    def test_own_private_allowed_without_changing_fact_text(self):
        task,raw,sources=setup();before=deepcopy(raw);r=with_access_decision(task,raw,sources)
        self.assertEqual(r['evidence']['facts'],raw['facts']);self.assertEqual(raw,before)
        p=r['evidence']['app_access_decision'];self.assertEqual(p['current_speaker']['name'],'Bram')
        self.assertEqual(p['current_listeners'],[{'id':'c','name':'Bram'}]);self.assertEqual(p['source_permissions']['s1']['permitted_audience_ids'],['c'])
        self.assertFalse(p['semantic_truth_verified']);self.assertNotIn('allow_everything',p)

    def test_group_or_other_person_never_gets_private_data_or_metadata(self):
        task,raw,sources=setup()
        for audience,speaker in [(['a','c'],'c'),(['a'],'a')]:
            t={**task,'audience_ids':audience,'actual_speaker_id':speaker};r=with_access_decision(t,raw,sources)
            self.assertEqual(len(r['evidence']['facts']),1);self.assertNotIn('s1',r['evidence']['source_headers'])
            self.assertNotIn('s1',r['evidence']['app_access_decision']['source_permissions']);self.assertNotIn('CANARY',str(r['evidence']))

    def test_mixed_support_fact_is_dropped_whole_not_repaired(self):
        task,raw,sources=setup();raw['facts']=[{'text':'Mixed CANARY and maps','sources':['s1','s2']}]
        task['audience_ids']=['a','c'];r=with_access_decision(task,raw,sources)
        self.assertEqual(r['evidence']['facts'],[]);self.assertEqual(r['evidence']['app_access_decision']['source_permissions'],{})

    def test_unknown_speaker_or_invalid_audience_refused(self):
        task,raw,sources=setup()
        for change in [{'actual_speaker_id':'unknown'},{'audience_ids':['a']},{'audience_ids':['c','c']}]:
            with self.assertRaises(ValueError):with_access_decision({**task,**change},raw,sources)

    def test_quarantined_deleted_and_unbound_sources_never_get_allowed_flags(self):
        task,raw,sources=setup()
        for flag in ['deleted','quarantined']:
            changed=deepcopy(sources);changed[0][flag]=True;r=with_access_decision(task,raw,changed)
            self.assertNotIn('s1',r['evidence']['app_access_decision']['source_permissions'])
        raw['facts'].append({'text':'unbound','sources':['made-up']});r=with_access_decision(task,raw,sources)
        self.assertNotIn('made-up',r['evidence']['source_headers'])

    def test_reporting_speaker_does_not_become_fact_subject(self):
        task,raw,sources=setup();r=with_access_decision(task,raw,sources)
        p=r['evidence']['app_access_decision']['source_permissions']['s2']
        self.assertEqual(p['source_speaker_id'],'a');self.assertNotIn('subject_id',p)
        self.assertEqual(r['evidence']['facts'][1]['text'],'Bram likes maps')

    def test_scope_or_source_change_changes_existing_request_snapshot(self):
        task,raw,sources=setup();first=with_access_decision(task,raw,sources)
        task2={**task,'audience_ids':['a','c']};second=with_access_decision(task2,raw,sources)
        self.assertNotEqual(snapshot(task,first['evidence']),snapshot(task2,second['evidence']))
        sources[0]['quarantined']=True;third=with_access_decision(task,raw,sources)
        self.assertNotEqual(snapshot(task,first['evidence']),snapshot(task,third['evidence']))
