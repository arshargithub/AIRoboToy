import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from tavi.speaker_evidence import Candidate,profile_revision
from tavi.identity_catalog import ProfileCatalog
from tavi.identity_policy import rank,fit_development,QualifiedPolicy
from tavi.live_identity import LiveIdentity

MODEL='a'*64
def vector(n):return [float(i==n) for i in range(512)]
def candidate(person,n):return Candidate(person,str(n+1).zfill(32),MODEL,hashlib.sha256(person.encode()).hexdigest(),tuple(vector(n)))


class CatalogTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
    def profile(self,person,n,category='family-enrollment'):
        p=self.root/category/str(n+1).zfill(32)/'profile.json';p.parent.mkdir(parents=True)
        body={'schema_version':1,'profile_id':p.parent.name,'person_id':person,'model_sha256':MODEL,'centroid':vector(n),
            'dimension':512,'status':'candidate_unqualified','recognition_enabled':False,'authorizes_personal_memory':False,
            'local_only':True,'threshold':None,'workflow_run':'fixture','clips':[{'pcm_sha256':hashlib.sha256(str(i).encode()).hexdigest()} for i in range(6)]}
        p.write_text(json.dumps(body));return p
    def catalog(self):return ProfileCatalog(self.root,guard=lambda:None,verify_run=lambda _:dict(state='finished',decision='pass'))
    def test_exact_single_versions_are_candidates_not_authority(self):
        self.profile('childone',0);self.profile('childtwo',1);c=self.catalog();state=c.refresh();self.assertEqual(len(c.candidates),2);self.assertFalse(state['recognition_enabled']);self.assertTrue(c.current())
    def test_multiple_versions_require_explicit_hash_selection(self):
        self.profile('childone',0);second=self.profile('childone',1);c=self.catalog();c.refresh();self.assertNotIn('childone',c.entries)
        (self.root/'selected-profiles.json').write_text(json.dumps({'childone':hashlib.sha256(second.read_bytes()).hexdigest()}));c.refresh();self.assertEqual(c.entries['childone']['path'],second)
    def test_file_change_revokes_cached_revision(self):
        p=self.profile('childone',0);c=self.catalog();c.refresh();p.write_text(p.read_text()+' ');self.assertFalse(c.current())
    def test_incomplete_collection_cannot_be_loaded(self):
        self.profile('childone',0);c=self.catalog();c.verify_run=lambda _:dict(state='running',decision=None);c.refresh();self.assertFalse(c.candidates)
    def test_historical_sessions_stay_excluded_from_heldout(self):
        p=self.profile('adultone',0,'imported-enrollment');d=json.loads(p.read_text());d['excluded_from_heldout_sessions']=['older-one','older-two'];p.write_text(json.dumps(d));c=self.catalog();c.refresh();self.assertEqual(c.excluded_sessions(),['older-one','older-two'])


class PolicyTests(unittest.TestCase):
    def test_low_score_small_margin_tie_and_quality_fail_are_unknown(self):
        scores=[{'person_id':'childone','cosine':.9},{'person_id':'childtwo','cosine':.3}]
        self.assertEqual(rank(scores,.8,.2,eligible=True),'childone');self.assertEqual(rank(scores,.95,.2,eligible=True),'unknown');self.assertEqual(rank(scores,.8,.7,eligible=True),'unknown');self.assertEqual(rank(scores,.8,.2,eligible=False),'unknown')
        self.assertEqual(rank([{'person_id':'childone','cosine':1},{'person_id':'childtwo','cosine':1}],.8,0,eligible=True),'unknown')
    def rows(self):
        people=['adultone','adulttwo','childtwo','childone'];rows=[]
        for p in people+['guest']:
            for n in range(20 if p=='guest' else 12):
                rows.append({'phase':'development','sample_id':p+str(n),'session_id':p,'pcm_sha256':hashlib.sha256((p+str(n)).encode()).hexdigest(),'eligible':True,'label_kind':'unknown' if p=='guest' else 'known','person_id':None if p=='guest' else p,'scores':[{'person_id':who,'cosine':.9 if p==who else .4 if p=='guest' else .2} for who in people]})
        return rows
    def test_development_needs_coverage_and_never_activates_identity(self):
        self.assertEqual(fit_development(self.rows()[:5],['adultone'])['status'],'needs_evidence')
        result=fit_development(self.rows(),['adultone','adulttwo','childtwo','childone']);self.assertEqual(result['status'],'development_candidate_only');self.assertFalse(result['recognition_enabled']);self.assertFalse(result['authorizes_personal_memory'])
    def test_heldout_or_duplicated_data_cannot_choose_cutoffs(self):
        rows=self.rows();rows[0]['phase']='heldout'
        with self.assertRaises(ValueError):fit_development(rows,['adultone'])
        rows=self.rows();rows[1]['pcm_sha256']=rows[0]['pcm_sha256']
        with self.assertRaises(ValueError):fit_development(rows,['adultone'])
    def test_unseparable_development_does_not_open_heldout(self):
        rows=self.rows()
        for r in rows:r['scores']=[{'person_id':p,'cosine':.9} for p in ['adultone','adulttwo','childtwo','childone']]
        self.assertEqual(fit_development(rows,['adultone','adulttwo','childtwo','childone'])['status'],'development_failed')
    def test_missing_policy_and_model_authored_flag_cannot_authorize(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'policy.json';catalog=SimpleNamespace(revision='b'*64)
            self.assertIsNone(QualifiedPolicy.load(p,catalog,MODEL));p.write_text(json.dumps({'qualified':True}))
            with self.assertRaises(ValueError):QualifiedPolicy.load(p,catalog,MODEL)


class Encoder:
    def __init__(self):self.lock=threading.Lock();self.block=None;self.cancelled=False
    def prepare(self):pass
    def encode(self,pcm):
        if self.block:self.block.wait(2)
        return {'pcm_sha256':hashlib.sha256(pcm).hexdigest(),'model_sha256':MODEL,'dimension':512,'embedding':vector(0),'quality':{'voiced_seconds':3}}
    def cancel(self):
        self.cancelled=True
        if self.block:self.block.set()
    def close(self):pass


class LiveIdentityTests(unittest.TestCase):
    def setUp(self):
        profiles=(candidate('childone',0),candidate('childtwo',1));self.valid=True
        self.catalog=SimpleNamespace(candidates=profiles,revision=profile_revision(profiles),current=lambda:self.valid)
        self.encoder=Encoder();self.voice=LiveIdentity(self.catalog,self.encoder,MODEL);self.addCleanup(self.voice.close);self.voice.reset('lease')
    def wait(self):
        for _ in range(200):
            with self.voice.lock:
                if self.voice.results:return
            time.sleep(.005)
        self.fail('Voice fixture did not finish')
    def test_highest_match_without_policy_stays_unknown(self):
        self.voice.submit('lease',1,b'\x01\x00'*40000);self.wait();r=self.voice.latch('lease',1);self.assertEqual(r.speaker_id,'unknown');self.assertEqual(r.reason,'uncalibrated_shadow_only')
    def test_missing_result_does_not_wait_or_inherit_a_previous_person(self):
        began=time.monotonic();r=self.voice.latch('lease',2);self.assertLess(time.monotonic()-began,.05);self.assertEqual(r.speaker_id,'unknown')
    def test_controlled_qualified_policy_binds_exact_pcm_and_catalog(self):
        self.voice.policy=SimpleNamespace(profiles_revision=self.catalog.revision,model_sha256=MODEL,threshold=.8,margin=.2,certificate_sha256='c'*64)
        pcm=b'\x01\x00'*150000;self.voice.submit('lease',1,pcm);self.wait();r=self.voice.latch('lease',1);self.assertEqual(r.speaker_id,'childone');self.assertEqual(r.turn.pcm_sha256,hashlib.sha256(pcm).hexdigest())
    def test_changed_profile_storage_revokes_a_finished_score(self):
        self.voice.submit('lease',1,b'\x01\x00'*40000);self.wait();self.valid=False;self.assertEqual(self.voice.latch('lease',1).reason,'profiles_or_storage_changed')
    def test_old_lease_and_late_work_cannot_reidentify_new_session(self):
        self.encoder.block=threading.Event();self.voice.submit('lease',1,b'\x01\x00'*40000)
        for _ in range(100):
            if self.voice.running:break
            time.sleep(.002)
        self.voice.reset('new-lease');self.assertTrue(self.encoder.cancelled);self.assertEqual(self.voice.latch('new-lease',1).speaker_id,'unknown');self.assertEqual(self.voice.latch('lease',1).reason,'stale_lease')
