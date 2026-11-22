import unittest
from dataclasses import asdict
from experiments.memory.subject_contract import Claim,admission_digest
from experiments.memory.typed_lookup import MemorySnapshot,source_digest
from experiments.memory.typed_narrative import elapsed_report,narrative_lookup,render_narrative

class NarrativeTests(unittest.TestCase):
    def snapshot(self, *, private_old=False, deleted=()):
        people={'p1':'Mira','p2':'Leo'};sources=[];rows=[]
        for i,(kind,value,audience) in enumerate([('preference','watermelon juice',['p1'] if private_old else list(people)),('preference','plum juice',list(people)),('withdraw','plum juice',list(people))],1):
            s={'id':str(i),'speaker_id':'p1','at':f'2026-05-0{i}T10:00:00Z','session':str(i),'audience_ids':audience,'text':value}
            c=Claim(id=str(i)+':0',source_id=str(i),subject_id='p1',slot='drink',value=value,kind=kind,relation='self',quote=value)
            sources.append(s);rows.append({'source_id':s['id'],'source_sha256':source_digest(s),'proposals':[asdict(c)],'validation':{'admissions':{c.id:admission_digest(c,s)},'decisions':[],'rejected':{}}})
        return MemorySnapshot(people,sources,rows,deleted_source_ids=deleted)

    def test_history_obeys_audience_asof_and_deletion(self):
        request={'operation':'preference','subject_id':'p1','slot':'drink'}
        at='2026-05-02T12:00:00Z'
        private=self.snapshot(private_old=True)
        shared=narrative_lookup(private,request,audience=['p1','p2'],as_of=at)
        self.assertNotIn('previous_preference',shared)
        solo=narrative_lookup(private,request,audience=['p1'],as_of=at)
        self.assertEqual(solo['previous_preference']['value'],'watermelon juice')
        deleted=narrative_lookup(self.snapshot(deleted=('1',)),request,audience=['p1'],as_of=at)
        self.assertNotIn('previous_preference',deleted)
        self.assertEqual(shared['status'],'supported') # later withdrawal not yet effective

    def test_withdrawal_recalled_without_inventing_a_cause(self):
        snapshot=self.snapshot();request={'operation':'preference','subject_id':'p1','slot':'drink'}
        result=narrative_lookup(snapshot,request,audience=['p1'],as_of='2026-05-04T12:00:00Z')
        answer=render_narrative({'status':'resolved','request':request},result,'p1',snapshot.people,as_of='2026-05-04T12:00:00Z')
        self.assertIn('plum juice',answer['text']);self.assertIn("isn't anymore",answer['text'])
        self.assertEqual(answer['source_ids'],['2','3']);self.assertNotIn('because',answer['text'])

    def test_elapsed_time_is_report_relative_not_wall_clock(self):
        self.assertEqual(elapsed_report('2026-05-23T10:00:00Z','2026-05-28T12:00:00Z'),'5 days ago')
        self.assertEqual(elapsed_report('2026-05-23T10:00:00Z','2026-11-04T12:00:00Z'),'about 5 months ago')
        with self.assertRaises(ValueError):elapsed_report('2026-05-23T10:00:00Z','2026-05-22T12:00:00Z')

    def test_insufficient_does_not_become_tentative_and_no_counts_in_speech(self):
        route={'status':'resolved','request':{'operation':'interests','subject_id':'p1','slot':'activity'}}
        result={'status':'evaluated','patterns':[{'activity':'paper folding','status':'insufficient_sessions','session_count':2,'source_ids':['1']}]}
        answer=render_narrative(route,result,'p1',{'p1':'Mira'},as_of='2026-05-23T10:00:00Z')
        self.assertIn("not sure",answer['text']);self.assertNotIn('conversation',answer['text']);self.assertNotIn('2',answer['text'])
