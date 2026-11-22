import copy
import hashlib
import importlib
import unittest

evaluate=importlib.import_module('experiments.speaker-id.identity_metrics').evaluate
MODEL='a'*64
PEOPLE=['adultone','childtwo','adulttwo','childone']


def sha(value):return hashlib.sha256(str(value).encode()).hexdigest()


def fixtures():
    enrollment=[{'person_id':p,'session_id':'enroll-'+p,'pcm_sha256':sha('enroll-'+p)} for p in PEOPLE]
    rows=[]
    for p in PEOPLE:
        for i in range(25):
            rows.append({'sample_id':p+str(i),'session_id':'held-'+p,'pcm_sha256':sha(p+str(i)),
                'model_sha256':MODEL,'label_kind':'known','person_id':p,'duration_ms':3000,'eligible':True,
                'decision':p,'memory_authorized':False})
    for kind,count in [('unknown',20),('short',10),('overlap',10)]:
        for i in range(count):
            rows.append({'sample_id':kind+str(i),'session_id':'held-'+kind,'pcm_sha256':sha(kind+str(i)),
                'model_sha256':MODEL,'label_kind':kind,'person_id':None,'duration_ms':500 if kind=='short' else 3000,
                'eligible':False,'decision':'unknown','memory_authorized':False})
    return rows,enrollment


class IdentityMetricsTests(unittest.TestCase):
    def run_rows(self,rows,enrollment=None,**kw):
        return evaluate(rows,model_sha256=MODEL,enrollment=fixtures()[1] if enrollment is None else enrollment,**kw)

    def test_complete_perfect_identity_is_never_full_E4_or_live_authority(self):
        rows,enroll=fixtures();result=self.run_rows(rows,enroll)
        self.assertEqual(result['identity_subscreen'],'pass');self.assertTrue(result['coverage_complete'])
        self.assertFalse(result['E4_accepted']);self.assertFalse(result['recognition_enabled']);self.assertFalse(result['authorizes_personal_memory'])

    def test_abstention_cannot_win_with_zero_wrong_assignments(self):
        rows,_=fixtures()
        for r in rows:r['decision']='unknown'
        result=self.run_rows(rows);self.assertEqual(result['known_correct_fraction'],0)
        self.assertEqual(result['unknown_rejection_fraction'],1);self.assertEqual(result['identity_subscreen'],'fail')

    def test_one_person_at_a_time_reports_missing_evidence_not_failure_or_pass(self):
        rows,enroll=fixtures();result=self.run_rows(rows[:25],enroll[:1])
        self.assertEqual(result['identity_subscreen'],'needs_evidence');self.assertIsNone(result['per_person']['childone']['correct_fraction'])

    def test_per_person_failure_not_hidden_by_overall_average(self):
        rows,_=fixtures()
        for r in rows[:4]:r['decision']='unknown'
        result=self.run_rows(rows);self.assertEqual(result['known_correct_fraction'],.96)
        self.assertEqual(result['per_person']['adultone']['correct_fraction'],.84);self.assertEqual(result['identity_subscreen'],'fail')

    def test_unknown_rows_do_not_dilute_confident_wrong_known_rate(self):
        rows,_=fixtures();rows[0]['decision']='childone';rows[1]['decision']='childone'
        for i in range(300):
            r=copy.deepcopy(rows[-1]);r.update(sample_id='extra'+str(i),pcm_sha256=sha('extra'+str(i)),label_kind='unknown');rows.append(r)
        result=self.run_rows(rows);self.assertEqual(result['known_confident_wrong_fraction'],.02)
        self.assertLess(result['all_samples_confident_wrong_fraction'],.01);self.assertEqual(result['identity_subscreen'],'fail')

    def test_unknown_rejection_boundary_and_overlap_memory_violation(self):
        rows,_=fixtures();rows[100]['decision']='adultone'
        self.assertEqual(self.run_rows(rows)['unknown_rejection_fraction'],.95)
        rows[101]['decision']='childone';self.assertEqual(self.run_rows(rows)['identity_subscreen'],'fail')
        rows,_=fixtures();rows[-1]['memory_authorized']=True
        self.assertFalse(self.run_rows(rows)['checks']['no_overlap_personal_memory_authorization'])

    def test_known_ineligible_retained_and_quality_labels_cannot_hide_missing_coverage(self):
        rows,_=fixtures();rows[0]['eligible']=False
        result=self.run_rows(rows);self.assertEqual(result['per_person']['adultone']['attempted'],25)
        self.assertEqual(result['per_person']['adultone']['ineligible'],1);self.assertFalse(result['coverage_complete'])

    def test_enrollment_development_duplicate_and_model_leakage_refused(self):
        rows,enroll=fixtures()
        for key,value in [('session_id','enroll-adultone'),('pcm_sha256',enroll[0]['pcm_sha256']),('model_sha256','b'*64)]:
            changed=copy.deepcopy(rows);changed[0][key]=value
            with self.assertRaises(ValueError):self.run_rows(changed)
        with self.assertRaises(ValueError):self.run_rows(rows+[rows[0]])
        with self.assertRaises(ValueError):self.run_rows(rows,development_sessions=['held-adultone'])

    def test_invalid_labels_and_uncertain_memory_are_not_authority(self):
        rows,_=fixtures()
        for key,value in [('eligible',1),('duration_ms',1000),('decision','visitor'),('person_id',None),('memory_authorized',None)]:
            changed=copy.deepcopy(rows);changed[0][key]=value
            with self.assertRaises(ValueError):self.run_rows(changed)
        rows[100]['memory_authorized']=True
        self.assertFalse(self.run_rows(rows)['checks']['no_uncertain_personal_memory_authorization'])

    def test_short_cases_cannot_substitute_for_all_overlap_evidence(self):
        rows,_=fixtures()
        for r in rows:
            if r['label_kind']=='overlap':r['label_kind']='short'
        self.assertFalse(self.run_rows(rows)['coverage_complete'])
