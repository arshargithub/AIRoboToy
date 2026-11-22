import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tavi.experiment_workflow import audit,begin,evaluate,finish,discover_runs


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'tavi').mkdir();(self.root/'tavi/worker.py').write_text('pinned source')
        (self.root/'docs').mkdir();(self.root/'docs/PAPRIKA_EXECUTION_PLAN.md').write_text('| L1 | approved local work |\n')
        (self.root/'input.json').write_text('frozen input')
        self.plan={'experiment_id':'LOCAL-01','work_item':'L1','hypothesis':'test',
            'configuration':{'model':'pinned'},'inputs':['input.json'],
            'criteria':[{'metric':'latency','max':500},{'metric':'quality_reviewed','equals':True}],
            'limits':{'maximum_additional_api_usd':0},'data_policy':'saved_audio_local',
            'next_actions':{k:'next '+k for k in ['pass','fail','needs_evidence','error']},
            'source_paths':['tavi/worker.py']}
        self.protocol=self.root/'protocol.json';self.protocol.write_text(json.dumps(self.plan))
        self.patch=patch('tavi.experiment_workflow.ROOT',self.root);self.patch.start();self.addCleanup(self.patch.stop)

    def test_default_discovery_keeps_local_runs(self):
        folder,_=begin(self.protocol)
        self.assertEqual(discover_runs(),[folder/'run.json'])

    def test_status_includes_configured_external_memory_evidence(self):
        local,_=begin(self.protocol)
        storage=self.root/'volume/PaprikaMemory'
        external=storage/'runs/scored/MEMORY-01/one/run.json'
        external.parent.mkdir(parents=True);external.write_text('{}')
        (self.root/'.tavi/memory-runtime.json').write_text(json.dumps({'root':str(storage)}))
        with patch.object(Path,'is_mount',return_value=True):
            self.assertEqual(set(discover_runs()),{local/'run.json',external})

    def test_missing_memory_drive_cannot_look_like_a_complete_audit(self):
        begin(self.protocol)
        (self.root/'.tavi/memory-runtime.json').write_text(json.dumps({'root':str(self.root/'volume/PaprikaMemory')}))
        with patch.object(Path,'is_mount',return_value=False):
            with self.assertRaisesRegex(ValueError,'drive unavailable'):discover_runs()

    def test_unknown_quality_is_not_a_pass_and_screen_does_not_accept_product(self):
        folder,_=begin(self.protocol)
        record=finish(folder,{'latency':100})
        self.assertEqual(record['decision']['outcome'],'needs_evidence')
        self.assertFalse(record['screen_passed']);self.assertFalse(record['product_accepted'])
        self.assertTrue(audit(folder)['valid'])

    def test_failed_bound_and_nan_cannot_pass(self):
        self.assertEqual(evaluate(self.plan,{'latency':501,'quality_reviewed':True})['outcome'],'fail')
        self.assertEqual(evaluate(self.plan,{'latency':float('nan'),'quality_reviewed':True})['outcome'],'needs_evidence')
        self.assertEqual(evaluate(self.plan,{'latency':100,'quality_reviewed':1})['outcome'],'fail')

    def test_source_or_protocol_edits_prevent_misbinding(self):
        folder,_=begin(self.protocol)
        (self.root/'tavi/worker.py').write_text('changed source')
        with self.assertRaisesRegex(ValueError,'source changed'):finish(folder,{})
        (folder/'protocol.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'Protocol hash'):audit(folder)

    def test_artifact_tampering_and_rewriting_finished_run_rejected(self):
        folder,_=begin(self.protocol);artifact=folder/'result.json';artifact.write_text('{}')
        finish(folder,{'latency':100,'quality_reviewed':True},artifacts=[artifact])
        self.assertEqual(audit(folder)['decision'],'pass')
        with self.assertRaisesRegex(ValueError,'immutable'):finish(folder,{})
        artifact.write_text('changed')
        with self.assertRaisesRegex(ValueError,'artifact hash'):audit(folder)

    def test_hidden_credentials_cannot_be_snapshotted(self):
        self.plan['source_paths']=['.env'];self.protocol.write_text(json.dumps(self.plan))
        with self.assertRaises(ValueError):begin(self.protocol)

    def test_local_recording_protocol_cannot_authorize_api_spend(self):
        self.plan['limits']['maximum_additional_api_usd']=1
        self.protocol.write_text(json.dumps(self.plan))
        with self.assertRaisesRegex(ValueError,'API spending'):begin(self.protocol)

    def test_future_adult_collection_requires_all_explicit_choices(self):
        self.plan['data_policy']='new_adult_audio_consent';self.protocol.write_text(json.dumps(self.plan))
        for consent in (None,{}, {'adult':True,'recording':True,'cloud':'yes'}):
            with self.assertRaisesRegex(ValueError,'explicit'):begin(self.protocol,consent=consent)
        folder,_=begin(self.protocol,consent={'adult':True,'recording':True,'cloud':False})
        record=json.loads((folder/'run.json').read_text());self.assertIs(record['consent']['cloud'],False)

    def test_manifest_binds_actual_input_files_not_just_their_filenames(self):
        import hashlib
        raw=self.root/'audio.wav';raw.write_bytes(b'frozen audio fixture')
        m=self.root/'input.json';m.write_text(json.dumps({'files':[{'path':'audio.wav','sha256':hashlib.sha256(raw.read_bytes()).hexdigest()}]}))
        self.plan['input_manifests']=['input.json'];self.protocol.write_text(json.dumps(self.plan))
        folder,_=begin(self.protocol);raw.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'inputs changed'):finish(folder,{})

    def test_unplanned_work_rejected_and_active_plan_snapshot_audited(self):
        self.plan['work_item']='Z9';self.protocol.write_text(json.dumps(self.plan))
        with self.assertRaisesRegex(ValueError,'active plan'):begin(self.protocol)
        self.plan['work_item']='L1';self.protocol.write_text(json.dumps(self.plan));folder,_=begin(self.protocol)
        (folder/'context/docs/PAPRIKA_EXECUTION_PLAN.md').write_text('rewritten plan')
        with self.assertRaisesRegex(ValueError,'plan context'):audit(folder)
