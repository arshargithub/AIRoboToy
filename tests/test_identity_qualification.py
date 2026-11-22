import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tavi.experiment_workflow import ROOT,begin as real_begin,digest,audit
from tavi.identity_policy import QualifiedPolicy
from tavi.identity_qualification import qualify
from tavi.speaker_profile import write_json
from tests.test_voice_calibration import Catalog

class IdentityQualificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.model=json.loads((ROOT/'experiments/speaker-id/model-manifest.json').read_text())['sha256'];self.catalog=Catalog(self.model)
        self.enrollment=[{'person_id':p,'session_id':'enroll-'+p,'pcm_sha256':hashlib.sha256(('enroll-'+p).encode()).hexdigest()} for p in self.catalog.entries]
        self.catalog.enrollment=lambda:self.enrollment;self.catalog.excluded_sessions=lambda:['historical-adult-session']
        for p in self.catalog.entries:
            path=self.root/(p+'-profile.json');write_json(path,{'controlled_fixture':True,'person_id':p});self.catalog.entries[p]={'path':path}
        self.cal=type('Calibration',(),{})();self.cal.root=self.root/'calibration';self.cal.catalog=self.catalog;self.cal.model=self.model;self.cal.root.mkdir()
        self.candidate={'threshold':.8,'margin':.2,'development_sessions':['development'],'development_pcm_sha256':['f'*64],'decision_code_sha256':digest(ROOT/'tavi/identity_policy.py'),'profiles_revision':self.catalog.revision,'model_sha256':self.model}
        write_json(self.cal.root/'development-policy.json',self.candidate)
        self.rows=[]
        for person in self.catalog.entries:
            for n in range(25):self.row('known',person,n)
        for kind,total in [('unknown',20),('short',10),('overlap',10)]:
            for n in range(total):self.row(kind,None,n)
        self.cal.corpus=lambda phase:self.rows
    def row(self,kind,person,n):
        name=f'{kind}-{person}-{n}';self.rows.append({'sample_id':name,'session_id':f'fresh-{kind}-{person}','pcm_sha256':hashlib.sha256(name.encode()).hexdigest(),'model_sha256':self.model,'phase':'heldout','label_kind':kind,'person_id':person,'duration_ms':800 if kind=='short' else 3000,'eligible':kind!='short','scores':[{'person_id':p,'cosine':.95 if p==person else .1} for p in self.catalog.entries]})
    def run_fixture(self):
        def bounded_begin(protocol,**kw):return real_begin(protocol,run_root=self.root/'runs')
        with patch('tavi.identity_qualification.discover_runs',return_value=[]),patch('tavi.identity_qualification.begin',side_effect=bounded_begin):return qualify(self.cal)
    def test_independent_pass_seals_exact_cutoffs_and_loader_recomputes(self):
        r=self.run_fixture();self.assertEqual(r['status'],'individual_identity_component_qualified');self.assertFalse(r['E4_accepted']);self.assertEqual(audit(r['run'])['decision'],'pass')
        policy=self.root/'identity-policy.json';loaded=QualifiedPolicy.load(policy,self.catalog,self.model);self.assertEqual(loaded.threshold,.8);self.assertEqual(loaded.margin,.2)
        data=json.loads(policy.read_text());data['threshold']=.2;write_json(policy,data)
        with self.assertRaises(ValueError):QualifiedPolicy.load(policy,self.catalog,self.model)
    def test_missing_coverage_does_not_start_scored_run(self):
        self.rows.pop();self.assertEqual(self.run_fixture()['status'],'heldout_evidence_needed');self.assertFalse((self.root/'runs').exists())
    def test_overlap_confident_match_fails_and_never_writes_certificate(self):
        for r in self.rows:
            if r['label_kind']=='overlap':r['scores'][0]['cosine']=.99
        r=self.run_fixture();self.assertEqual(r['status'],'identity_component_failed');self.assertEqual(audit(r['run'])['decision'],'fail');self.assertFalse((self.root/'identity-policy.json').exists());self.assertEqual(self.run_fixture(),r)
    def test_development_reuse_is_rejected_not_relabelled_independent(self):
        self.rows[0]['session_id']='development'
        r=self.run_fixture();self.assertEqual(r['status'],'identity_component_error');self.assertEqual(audit(r['run'])['decision'],'error')
        self.assertFalse((self.root/'identity-policy.json').exists())
    def test_profile_change_does_not_reuse_previous_pass_pointer(self):
        self.run_fixture();self.catalog.revision='b'*64;self.assertEqual(self.run_fixture()['status'],'qualification_inputs_changed')
