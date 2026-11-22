from dataclasses import FrozenInstanceError, replace
import json
import unittest
from tavi.speaker_evidence import Candidate, TurnKey, compare_shadow, profile_revision

MODEL='a'*64


def vector(index=0):
    v=[0.0]*512;v[index]=1.0;return v


def candidate(person='adultone', index=0):
    return Candidate(person, ('1' if person=='adultone' else '2')*32, MODEL, ('3' if person=='adultone' else '4')*64, tuple(vector(index)))


class SpeakerEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.turn=TurnKey('session-one','capture-one','b'*64,0)
        self.profiles=(candidate(),candidate('adulttwo',1))

    def evidence(self, **kwargs):
        return compare_shadow(self.turn,vector(),MODEL,self.profiles,quality_eligible=True,**kwargs)

    def test_exact_match_is_diagnostic_only_never_personal_authorization(self):
        e=self.evidence();self.assertEqual(e.scores[0].person_id,'adultone');self.assertEqual(e.scores[0].cosine,1)
        self.assertEqual(e.scores[1].cosine,0);self.assertEqual(e.speaker_id,'unknown')
        self.assertFalse(e.authorizes_personal_memory);self.assertFalse(e.authorizes_learning)
        self.assertEqual(e.reason,'uncalibrated_shadow_only')

    def test_vectors_profiles_and_results_are_immutable_snapshots(self):
        values=vector();p=Candidate('adultone','1'*32,MODEL,'c'*64,values);values[0]=0
        self.assertEqual(p.centroid[0],1)
        e=self.evidence()
        for obj,key,val in [(e,'reason','known'),(e,'speaker_id','adultone'),(p,'person_id','childone'),(self.turn,'scope_epoch',1)]:
            with self.assertRaises((FrozenInstanceError,AttributeError)):setattr(obj,key,val)

    def test_every_turn_scope_and_profile_revision_must_still_match(self):
        e=self.evidence();self.assertIs(e.require_current(self.turn,MODEL,self.profiles),e)
        for turn in [replace(self.turn,session_id='new'),replace(self.turn,capture_id='new'),replace(self.turn,pcm_sha256='c'*64),replace(self.turn,scope_epoch=1)]:
            with self.assertRaises(ValueError):e.require_current(turn,MODEL,self.profiles)
        for profiles in [(),(replace(self.profiles[0],profile_sha256='d'*64),self.profiles[1]),(replace(self.profiles[0],centroid=tuple(vector(2))),self.profiles[1])]:
            with self.assertRaises(ValueError):e.require_current(self.turn,MODEL,profiles)
        with self.assertRaises(ValueError):e.require_current(self.turn,'f'*64,self.profiles)

    def test_bad_quality_missing_and_incompatible_profiles_never_score(self):
        for profiles,quality,reason in [(self.profiles,False,'quality_unqualified'),((),True,'no_profiles'),((replace(self.profiles[0],model_sha256='e'*64),),True,'incompatible_model')]:
            e=compare_shadow(self.turn,None,MODEL,profiles,quality_eligible=quality)
            self.assertEqual(e.reason,reason);self.assertEqual(e.scores,());self.assertEqual(e.speaker_id,'unknown')

    def test_ties_and_opposite_vectors_do_not_force_a_person(self):
        same=(candidate(),replace(candidate('adulttwo'),centroid=tuple(vector())))
        e=compare_shadow(self.turn,vector(),MODEL,same,quality_eligible=True)
        self.assertEqual([s.cosine for s in e.scores],[1,1]);self.assertEqual(e.speaker_id,'unknown')
        opposite=[-x for x in vector()];e=compare_shadow(self.turn,opposite,MODEL,(candidate(),),quality_eligible=True)
        self.assertEqual(e.scores[0].cosine,-1);self.assertEqual(e.speaker_id,'unknown')

    def test_invalid_dimension_nan_boolean_and_zero_vectors_rejected(self):
        for values in [[0]*512,vector()[:-1],[float('nan')]+[0]*511,[True]+[0]*511,[float('inf')]+[0]*511]:
            with self.assertRaises(ValueError):compare_shadow(self.turn,values,MODEL,self.profiles,quality_eligible=True)
        with self.assertRaises(ValueError):compare_shadow(self.turn,vector(),MODEL,self.profiles,quality_eligible=1)

    def test_candidate_files_must_be_local_and_unqualified(self):
        p={'schema_version':1,'person_id':'adultone','profile_id':'1'*32,'model_sha256':MODEL,'dimension':512,'centroid':vector(),
           'status':'candidate_unqualified','recognition_enabled':False,'authorizes_personal_memory':False,'threshold':None,'local_only':True}
        raw=json.dumps(p).encode();first=Candidate.from_bytes(raw)
        self.assertEqual(first.centroid[0],1);self.assertNotEqual(first.profile_sha256,Candidate.from_bytes(raw+b' ').profile_sha256)
        for key,value in [('recognition_enabled',True),('authorizes_personal_memory',True),('local_only',False),('threshold',.8),('status','active')]:
            with self.assertRaises(ValueError):Candidate.from_bytes(json.dumps({**p,key:value}).encode())
        for value in [[],None,{**p,'schema_version':True},{k:v for k,v in p.items() if k!='centroid'}]:
            with self.assertRaises(ValueError):Candidate.from_bytes(json.dumps(value).encode())

    def test_duplicate_people_profiles_and_incompatible_identifiers_rejected(self):
        for profiles in [(candidate(),candidate()),(candidate(),replace(candidate('adulttwo'),profile_id='1'*32))]:
            with self.assertRaises(ValueError):profile_revision(profiles)
        with self.assertRaises(ValueError):TurnKey('session','capture','not-a-hash',0)
        with self.assertRaises(ValueError):TurnKey('session','capture','a'*64,True)
        with self.assertRaises(ValueError):candidate('unknown')

    def test_profile_order_changes_no_identity_or_snapshot_revision(self):
        before=self.evidence();after=compare_shadow(self.turn,vector(),MODEL,tuple(reversed(self.profiles)),quality_eligible=True)
        self.assertEqual(before,after)

    def test_normalization_makes_similarity_independent_of_vector_scale(self):
        e=compare_shadow(self.turn,[x*7 for x in vector()],MODEL,self.profiles,quality_eligible=True)
        self.assertEqual(e,self.evidence())
