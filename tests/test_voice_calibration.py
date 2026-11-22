import hashlib,json,math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tavi.voice_calibration import VoiceCalibration,CONSENT
from tavi.identity_catalog import PEOPLE
from tavi.speaker_evidence import Candidate,profile_revision
from tavi.speaker_profile import ROOT


class Catalog:
    def __init__(self,model):
        self.entries={p:{} for p in PEOPLE};self.candidates=tuple(Candidate(p,str(i+1).zfill(32),model,hashlib.sha256(p.encode()).hexdigest(),tuple(float(j==i) for j in range(512))) for i,p in enumerate(PEOPLE));self.revision=profile_revision(self.candidates)
    def refresh(self):return self.status()
    def status(self):return {'people':[{'person_id':p,**r,'enrolled':p in self.entries,'examples':6} for p,r in PEOPLE.items()]}
    def enrollment(self):return []


class Encoder:
    def __init__(self,model):self.model=model;self.calls=0;self.error=None
    def encode(self,pcm):
        self.calls+=1
        if self.error:raise ValueError(self.error)
        return {'pcm_sha256':hashlib.sha256(pcm).hexdigest(),'model_sha256':self.model,'dimension':512,'embedding':[1.]+[0.]*511,'quality':{'voiced_seconds':3,'rms':.02,'clipped_fraction':0}}


class VoiceCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)/'calibration'
        self.model=json.loads((ROOT/'experiments/speaker-id/model-manifest.json').read_text())['sha256'];self.encoder=Encoder(self.model);self.catalog=Catalog(self.model)
        self.cal=VoiceCalibration(self.catalog,self.encoder,root=self.root,guard=lambda:None)
        self.body={'person_id':'childone','phase':'development','consent':CONSENT,'adult':True,'subject_willing':True,'alone':True,'local_only':True,'retain_audio':True,'supervised':True,'own_voice':False,'outside_family':False}
    def begin(self,body=None):return self.cal.begin(body or self.body)['session']
    def record(self,token,n,person='childone',pcm=None):
        state=self.cal.state(token,person)
        return self.cal.attempt(token,person,str(n+1).zfill(32),state['next_prompt']['id'],pcm or bytes([n+1,0])*40000)
    def choices(self,token,person='childone'):return {a['id']:'keep' for a in self.cal.state(token,person)['attempts'] if a['outcome'] in ('clear','short_control') and a['review']!='exclude'}
    def policy(self):
        from tavi.experiment_workflow import digest
        self.root.mkdir(exist_ok=True);(self.root/'development-policy.json').write_text(json.dumps({'status':'development_candidate_only','profiles_revision':self.catalog.revision,'model_sha256':self.model,'decision_code_sha256':digest(ROOT/'tavi/identity_policy.py')}))
    def test_missing_consent_never_creates_visit_or_encodes(self):
        for change in ({'adult':False},{'subject_willing':False},{'alone':False},{'retain_audio':None},{'local_only':False},{'supervised':False}):
            with self.assertRaises(ValueError):self.cal.begin({**self.body,**change})
        self.assertFalse(self.root.exists());self.assertEqual(self.encoder.calls,0)
    def test_known_subject_guest_and_heldout_require_proper_roles(self):
        with self.assertRaises(ValueError):self.cal.begin({**self.body,'person_id':'guest','supervised':False,'own_voice':True})
        with self.assertRaises(ValueError):self.cal.begin({**self.body,'phase':'heldout','different_occasion':True})
        body={**self.body,'person_id':'adultone','supervised':False,'own_voice':True};token=self.begin(body);self.assertEqual(self.cal.state(token,'adultone')['name'],'Adult One')
        with self.assertRaises(ValueError):self.cal.state(token,'childone')
    def test_reviewed_visit_persists_examples_without_enrollment_or_authority(self):
        token=self.begin()
        for n in range(6):self.record(token,n)
        self.assertEqual(self.cal.progress()['childone']['development'],0)
        state=self.cal.review(token,'childone',self.choices(token),True,finish_visit=True);self.assertTrue(state['complete']);self.assertEqual(state['kept'],6);self.assertFalse(state['recognition_enabled']);self.assertEqual(self.cal.progress()['childone']['development'],6);self.assertFalse(list(self.root.rglob('profile.json')))
        rows=self.cal.corpus('development');self.assertEqual(len(rows),6);self.assertTrue(all(r['phase']=='development' for r in rows))
    def test_short_or_duplicate_audio_is_not_counted_twice(self):
        token=self.begin();pcm=b'\x01\x00'*40000;self.record(token,0,pcm=pcm);self.record(token,1,pcm=pcm)
        state=self.cal.state(token,'childone');self.assertEqual(state['attempts'][1]['outcome'],'reused');self.assertEqual(state['eligible'],1);self.assertEqual(self.encoder.calls,1)
    def test_same_request_retry_is_idempotent_and_changed_pcm_rejected(self):
        token=self.begin();state=self.record(token,0);p=state['attempts'][0]['prompt_id'];self.cal.attempt(token,'childone','1'.zfill(32),p,b'\x01\x00'*40000);self.assertEqual(self.encoder.calls,1)
        with self.assertRaises(ValueError):self.cal.attempt(token,'childone','1'.zfill(32),p,b'\x02\x00'*40000)
    def test_technical_error_keeps_same_question_and_does_not_save_bad_example(self):
        token=self.begin();self.encoder.error='Pinned model unavailable'
        with self.assertRaises(ValueError):self.record(token,0)
        self.assertEqual(self.cal.state(token,'childone')['total'],0);self.encoder.error=None;self.assertEqual(self.record(token,0)['eligible'],1)
    def test_exclusion_deletes_only_its_provisional_audio_and_retry_is_safe(self):
        token=self.begin();self.record(token,0);folder,v=self.cal.folder(token,'childone');file=folder/v['attempts'][0]['reference_file'];choices=self.choices(token);choices[next(iter(choices))]='exclude'
        self.cal.review(token,'childone',choices,True);self.assertFalse(file.exists());self.cal.review(token,'childone',choices,True,finish_visit=True);self.assertEqual(self.cal.state(token,'childone')['kept'],0)
    def test_max_twelve_attempts_in_short_visit(self):
        token=self.begin()
        for n in range(6):self.record(token,n)
        self.cal.review(token,'childone',self.choices(token),True)
        for n in range(6,12):self.record(token,n)
        with self.assertRaises(ValueError):self.record(token,12)
    def test_private_state_never_exposes_vectors_or_paths(self):
        token=self.begin();state=self.record(token,0);serialized=json.dumps(state);self.assertNotIn('embedding',serialized);self.assertNotIn('reference_file',serialized)
        folder,_=self.cal.folder(token,'childone');self.assertEqual(folder.stat().st_mode&0o777,0o700)
        for file in folder.iterdir():self.assertEqual(file.stat().st_mode&0o777,0o600)
    def test_short_and_overlap_controls_have_independent_labels_not_speaker_truth(self):
        self.policy();body={**self.body,'person_id':'short','phase':'heldout','different_occasion':True,'supervised':False,'own_voice':True};token=self.begin(body)
        state=self.record(token,0,person='short',pcm=b'\x01\x00'*15872);self.assertEqual(state['attempts'][0]['outcome'],'short_control');self.assertEqual(self.encoder.calls,0)
        self.cal.review(token,'short',self.choices(token,'short'),True,finish_visit=True);row=self.cal.corpus('heldout')[0];self.assertEqual(row['label_kind'],'short');self.assertFalse(row['eligible']);self.assertIsNone(row['person_id'])
        overlap={**self.body,'person_id':'overlap','phase':'heldout','different_occasion':True,'alone':False,'two_speakers_agree':True};token=self.begin(overlap);self.record(token,1,person='overlap');self.cal.review(token,'overlap',self.choices(token,'overlap'),True,finish_visit=True)
        row=[r for r in self.cal.corpus('heldout') if r['label_kind']=='overlap'][0];self.assertTrue(row['eligible']);self.assertIsNone(row['person_id']);self.assertTrue(row['scores'],'Overlap labels cannot be passed into the scoring policy to force abstention')
    def test_skip_unfinished_is_not_a_recording_or_repeated_question(self):
        token=self.begin();state=self.cal.state(token,'childone');prompt=state['next_prompt']['id'];state=self.cal.skip(token,'childone','f'*32,prompt);self.assertEqual(state['total'],1);self.assertEqual(state['eligible'],0);self.assertNotEqual(state['next_prompt']['id'],prompt);self.assertEqual(self.encoder.calls,0)
    def test_missing_person_profile_blocks_recording_but_keeps_existing_other_data(self):
        self.catalog.entries.pop('childone')
        with self.assertRaises(ValueError):self.begin()
        self.assertFalse(self.root.exists())

    def test_heldout_start_locks_fit_even_before_visit_completed(self):
        self.policy();self.begin({**self.body,'phase':'heldout','different_occasion':True})
        self.assertEqual(self.cal.fit()['status'],'cutoffs_frozen_heldout_started')
    def test_abandoned_visits_count_towards_limit(self):
        for _ in range(4):self.begin()
        with self.assertRaises(ValueError):self.begin()
    def test_audio_written_before_failed_draft_save_can_retry_exact_pcm(self):
        token=self.begin();from tavi.speaker_profile import write_json
        def fail_visit(path,value):
            if value.get('attempts'):raise OSError('controlled draft failure')
            return write_json(path,value)
        with patch('tavi.voice_calibration.write_json',side_effect=fail_visit):
            with self.assertRaises(OSError):self.record(token,0)
        self.assertEqual(self.cal.state(token,'childone')['total'],0)
        self.assertEqual(len(list(self.root.rglob('*.wav'))),1)
        self.assertEqual(self.record(token,0)['total'],1)
    def test_completed_draft_with_failed_seal_can_retry_without_recording(self):
        token=self.begin();self.record(token,0);calls=[]
        def seal(folder,v):
            calls.append(v['session_id'])
            if len(calls)==1:raise OSError('controlled seal failure')
        self.cal.seal=seal
        with self.assertRaises(OSError):self.cal.review(token,'childone',self.choices(token),True,finish_visit=True)
        self.cal.review(token,'childone',self.choices(token),True,finish_visit=True)
        self.assertEqual(len(calls),2);self.assertEqual(self.encoder.calls,1)
