import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tavi.family_collection import FamilyCollection,CONSENT,PROMPTS

MODEL='a'*64


class Encoder:
    def __init__(self):self.calls=[];self.error=None
    def encode(self,pcm):
        self.calls.append(pcm)
        if self.error:raise self.error
        return {'embedding':[1.]+[0.]*511,'dimension':512,'model_sha256':MODEL,
                'pcm_sha256':hashlib.sha256(pcm).hexdigest(),'quality':{'voiced_seconds':3,'duration_seconds':len(pcm)/32000,'rms':.05,'clipped_fraction':0}}


class FamilyCollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)/'family'
        self.encoder=Encoder();self.bound=[]
        self.c=FamilyCollection(root=self.root,encoder=self.encoder,guard=lambda:None,bind=lambda b:self.bound.append(dict(b)),model_sha256=MODEL)
        self.body={'person_id':'childone','consent':CONSENT,'adult_confirmed':True,'subject_willing':True,'alone':True,'supervised':True,'processing':'local-only','retain_audio':False}
    def begin(self):return self.c.begin(self.body)['session']
    def record(self,token,n,pcm=None):
        return self.c.attempt(token,self.body['person_id'],str(n+1).zfill(32),PROMPTS[n]['id'],pcm if pcm is not None else bytes([n+1,0])*16000,{})
    def review(self,token,exclude=None):
        state=self.c.state(token,self.body['person_id']);choices={a['id']:('other_voice' if a['id']==exclude else 'keep') for a in state['attempts'] if a['outcome']=='clear' and a['review']!='exclude'}
        return self.c.review(token,self.body['person_id'],choices,True),choices

    def test_child_consent_and_no_cloud_before_binding_files_or_encoder(self):
        for body in [{},{**self.body,'adult_confirmed':False},{**self.body,'subject_willing':False},{**self.body,'supervised':False},{**self.body,'alone':False},{**self.body,'processing':'cloud'},{**self.body,'retain_audio':None},{**self.body,'person_id':'adultone'}]:
            with self.assertRaises(ValueError):self.c.begin(body)
        self.assertEqual(self.bound,[]);self.assertFalse(self.root.exists());self.assertEqual(self.encoder.calls,[])

    def test_startup_repair_requires_new_consent_and_preserves_failed_binding(self):
        old=Path(self.temp.name)/'failed';old.mkdir();(old/'run.json').write_text(json.dumps({'state':'finished','error':'microphone_startup_processor_not_registered'}))
        new=Path(self.temp.name)/'repaired';new.mkdir();(new/'run.json').write_text(json.dumps({'state':'running'}))
        self.c.bind=lambda b:old
        token=self.begin();folder,draft=self.c.folder(token,'childone')
        self.c.bind=lambda b:new
        with self.assertRaises(ValueError):self.c.begin({**self.body,'adult_confirmed':False},token)
        self.assertEqual(self.c.folder(token,'childone')[1]['workflow_run'],str(old))
        self.c.begin(self.body,token);draft=self.c.folder(token,'childone')[1]
        self.assertEqual(draft['workflow_run'],str(new));self.assertEqual(draft['previous_workflow_runs'],[str(old)])
        self.assertEqual(draft['attempts'],[]);self.assertEqual(json.loads((old/'run.json').read_text())['state'],'finished')
        self.c.begin(self.body,token);self.assertEqual(len(self.c.folder(token,'childone')[1]['previous_workflow_runs']),1)

    def test_startup_repair_does_not_rebind_samples_or_other_failures(self):
        old=Path(self.temp.name)/'failed';old.mkdir();(old/'run.json').write_text(json.dumps({'state':'running'}))
        self.c.bind=lambda b:old;token=self.begin();self.record(token,0)
        (old/'run.json').write_text(json.dumps({'state':'finished','error':'microphone_startup_processor_not_registered'}))
        with self.assertRaises(ValueError):self.c.begin(self.body,token)
        self.assertEqual(self.c.state(token,'childone')['total'],1)
        folder,draft=self.c.folder(token,'childone');draft['attempts']=[];self.c._write(folder/'draft.json',draft)
        (old/'run.json').write_text(json.dumps({'state':'finished','error':'other_failure'}))
        with self.assertRaises(ValueError):self.c.begin(self.body,token)

    def test_adulttwo_requires_own_voice_and_can_record_without_child_supervision(self):
        self.body.update(person_id='adulttwo',supervised=False,own_voice=True)
        with self.assertRaises(ValueError):self.c.begin({**self.body,'own_voice':False})
        token=self.begin();self.assertFalse(self.c.state(token,'adulttwo')['child']);self.assertEqual(self.c.state(token,'adulttwo')['name'],'Adult Two')

    def test_six_approved_samples_candidate_only_no_raw_or_memory_authority(self):
        token=self.begin()
        for n in range(6):self.record(token,n)
        with self.assertRaises(ValueError):self.c.finish(token,'childone')
        self.review(token);self.assertTrue(self.c.finish(token,'childone')['complete'])
        folder,_=self.c.folder(token,'childone');profile=json.loads((folder/'profile.json').read_text())
        self.assertEqual(len(profile['clips']),6);self.assertFalse(profile['recognition_enabled']);self.assertFalse(profile['authorizes_personal_memory']);self.assertIsNone(profile['threshold'])
        self.assertFalse(list(folder.glob('*.wav')));self.assertNotIn('embedding',str(self.c.state(token,'childone')))

    def test_short_and_known_quality_failures_advance_to_fresh_prompt(self):
        token=self.begin();self.record(token,0,b'\x01\x00'*100)
        self.encoder.error=ValueError('The recording is too quiet. Move a little closer and record again.');state=self.record(token,1)
        self.assertEqual([a['outcome'] for a in state['attempts']],['short','quiet']);self.assertEqual(state['next_prompt']['id'],PROMPTS[2]['id']);self.assertEqual(state['eligible'],0)

    def test_technical_error_does_not_discard_advance_or_force_new_recording(self):
        token=self.begin();self.encoder.error=ValueError('Pinned model changed')
        with self.assertRaises(ValueError):self.record(token,0)
        self.assertEqual(self.c.state(token,'childone')['total'],0);self.encoder.error=None;self.assertEqual(self.record(token,0)['eligible'],1)

    def test_retry_same_id_is_idempotent_and_same_pcm_new_id_not_independent(self):
        token=self.begin();pcm=b'\x01\x00'*16000;self.record(token,0,pcm);self.record(token,0,pcm)
        self.assertEqual(len(self.encoder.calls),1)
        with self.assertRaises(ValueError):self.record(token,0,b'\x02\x00'*16000)
        state=self.record(token,1,pcm);self.assertEqual(state['attempts'][-1]['outcome'],'duplicate');self.assertEqual(state['eligible'],1)

    def test_person_specific_tokens_and_retention_cannot_be_switched(self):
        token=self.begin()
        for other in ('childtwo','adulttwo'):
            with self.assertRaises(ValueError):self.c.state(token,other)
        with self.assertRaises(ValueError):self.c.begin({**self.body,'retain_audio':True},token)
        self.record(token,0);self.c.pause(token,'childone');self.c.begin(self.body,token)
        self.assertEqual(self.c.state(token,'childone')['total'],1);self.assertFalse(self.c.state(token,'childone')['paused'])

    def test_parent_exclusion_discards_temporary_raw_vector_and_retry_safe(self):
        self.body['retain_audio']=True;token=self.begin()
        for n in range(6):self.record(token,n)
        folder,d=self.c.folder(token,'childone');excluded=d['attempts'][0]['id'];old_file=folder/d['attempts'][0]['reference_file']
        self.assertTrue(old_file.is_file());state,choices=self.review(token,excluded)
        self.assertEqual(state['kept'],5);self.assertFalse(old_file.exists())
        self.assertEqual(self.c.review(token,'childone',choices,True)['kept'],5)
        _,d=self.c.folder(token,'childone');self.assertNotIn('embedding',d['attempts'][0]);self.assertNotIn('reference_file',d['attempts'][0])
        self.assertEqual(folder.stat().st_mode&0o777,0o700)
        for file in folder.iterdir():self.assertEqual(file.stat().st_mode&0o777,0o600)

    def test_parent_attestation_and_no_promotion_of_bad_turns(self):
        token=self.begin();self.record(token,0,b'')
        with self.assertRaises(ValueError):self.c.review(token,'childone',{},False)
        with self.assertRaises(ValueError):self.c.review(token,'childone',{'1'.zfill(32):'keep'},True)

    def test_cleanup_failure_blocks_finalization_and_same_review_can_retry(self):
        self.body['retain_audio']=True;token=self.begin()
        for n in range(6):self.record(token,n)
        choices={a['id']:('skip' if a['number']==1 else 'keep') for a in self.c.state(token,'childone')['attempts']}
        with patch('pathlib.Path.unlink',side_effect=OSError('drive lost')):
            with self.assertRaises(ValueError):self.c.review(token,'childone',choices,True)
        self.assertFalse(self.c.state(token,'childone')['reviewed'])
        self.assertTrue(self.c.review(token,'childone',choices,True)['reviewed'])

    def test_skipping_interrupted_turn_never_erases_already_committed_useful_sample(self):
        token=self.begin();state=self.record(token,0);a=state['attempts'][0]
        self.c.skip(token,'childone',a['id'],a['prompt_id'],a['pcm_sha256']);self.assertEqual(self.c.state(token,'childone')['eligible'],1)
        self.c.skip(token,'childone','2'.zfill(32),PROMPTS[1]['id'],hashlib.sha256(b'').hexdigest())
        self.assertEqual(self.c.state(token,'childone')['total'],2)

    def test_twelve_turn_sitting_bound_and_explicit_new_sitting_keeps_old_samples(self):
        token=self.begin()
        for n in range(6):self.record(token,n,b'')
        self.review(token);self.c.more(token,'childone')
        for n in range(6,12):self.record(token,n,b'')
        self.review(token)
        with self.assertRaises(ValueError):self.c.more(token,'childone')
        self.c.pause(token,'childone');state=self.c.begin({**self.body,'new_sitting':True},token)
        self.assertEqual(state['sitting_start'],12);self.assertEqual(state['next_prompt']['id'],PROMPTS[12]['id']);self.assertEqual(state['total'],12)

    def test_corrupt_reference_blocks_profile_and_existing_data_is_preserved(self):
        self.body['retain_audio']=True;token=self.begin()
        for n in range(6):self.record(token,n)
        self.review(token);folder,d=self.c.folder(token,'childone');file=folder/d['attempts'][0]['reference_file'];file.write_bytes(b'corrupted')
        with self.assertRaises(ValueError):self.c.finish(token,'childone')
        self.assertFalse((folder/'profile.json').exists());self.assertEqual(file.read_bytes(),b'corrupted')

    def test_completed_profile_and_draft_remain_immutable_on_finish_pause_retry(self):
        token=self.begin()
        for n in range(6):self.record(token,n)
        self.review(token);self.c.finish(token,'childone');folder,_=self.c.folder(token,'childone')
        before=[(folder/n).read_bytes() for n in ('draft.json','profile.json')]
        self.c.finish(token,'childone');self.c.pause(token,'childone')
        self.assertEqual(before,[(folder/n).read_bytes() for n in ('draft.json','profile.json')])

    def test_new_sitting_does_not_mutate_finished_twelve_turn_profile(self):
        token=self.begin()
        for n in range(6):self.record(token,n,b'')
        self.review(token);self.c.more(token,'childone')
        for n in range(6,12):self.record(token,n)
        self.review(token);self.c.finish(token,'childone');folder,_=self.c.folder(token,'childone');before=(folder/'draft.json').read_bytes()
        self.c.begin({**self.body,'new_sitting':True},token);self.assertEqual((folder/'draft.json').read_bytes(),before)

    def test_only_two_explicit_sittings_per_collection(self):
        token=self.begin();self.c.pause(token,'childone');self.c.begin({**self.body,'new_sitting':True},token);self.c.pause(token,'childone')
        with self.assertRaises(ValueError):self.c.begin({**self.body,'new_sitting':True},token)

    def test_drive_loss_during_encoding_cannot_persist_result_or_advance(self):
        token=self.begin();available=[True];original=self.encoder.encode
        def guard():
            if not available[0]:raise ValueError('Reconnect the external drive')
        def encode(pcm):
            result=original(pcm);available[0]=False;return result
        self.c.guard=guard;self.encoder.encode=encode
        with self.assertRaises(ValueError):self.record(token,0)
        available[0]=True;self.assertEqual(self.c.state(token,'childone')['total'],0)

    def test_reference_path_escape_cannot_delete_or_read_unrelated_file(self):
        self.body['retain_audio']=True;token=self.begin();self.record(token,0);folder,draft=self.c.folder(token,'childone')
        outside=self.root/'keep-me.txt';outside.write_text('unrelated history');draft['attempts'][0]['reference_file']='../keep-me.txt'
        (folder/'draft.json').write_text(json.dumps(draft))
        with self.assertRaises(ValueError):self.c.audio(token,'childone',draft['attempts'][0]['id'])
        with self.assertRaises(ValueError):self.c.review(token,'childone',{draft['attempts'][0]['id']:'skip'},True)
        self.assertEqual(outside.read_text(),'unrelated history')
