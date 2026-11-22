import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments.memory.learning_queue import LearningQueue
from tavi.memory_generation import native_directory
from tavi.recovery_bundle import create_bundle, verify_bundle, restore_bundle, rebuild_plan


class RecoveryBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.bank=self.root/'bank';self.bank.mkdir()
        native_directory(self.bank,source_realm='fixture')
        self.q=LearningQueue(self.bank/'learning.sqlite3');self.addCleanup(self.q.close)
        scope={'session_id':'fiction','task':{'actual_speaker_id':'a','people':{'a':'Mira'},'audience_ids':['a'],'conversation_at':'2026-11-09T12:00:00Z'}}
        self.ids=[]
        for i in range(4):
            self.ids.append(self.q.capture(scope,None,'Fictional event '+str(i),str(i))['source_id'])
            if i<2:
                job=self.q.claim()
                if i==0:self.q.complete(job)
                else:self.q.note_work(job,'dispatched');self.q.note_work(job,'ambiguous')
        self.q.revoke(self.ids[-1])
    def bundle(self):return create_bundle(self.bank,self.root,source_realm='fixture')
    def test_bundle_restores_authority_and_ambiguity_without_activating_or_replaying(self):
        bundle=self.bundle();restored=restore_bundle(bundle,self.root);plan=rebuild_plan(restored,current_queue=self.q.path)
        self.assertEqual(plan['status'],'needs_job_reconciliation')
        self.assertEqual(plan['completed_source_candidates'],self.ids[:1]);self.assertEqual(plan['ambiguous_not_replayed'],self.ids[1:2])
        self.assertEqual(plan['pending_not_replayed'],self.ids[2:3]);self.assertEqual(plan['excluded_revoked'],self.ids[3:])
        self.assertFalse(plan['can_activate_live']);self.assertFalse(plan['automatic_replay_allowed'])
        self.assertEqual(self.q.working(),1)
        with self.assertRaisesRegex(ValueError,'Offline restored'):LearningQueue(restored/'queue.sqlite3')
        self.assertFalse((restored/'native-generation.json').exists())
    def test_later_revocation_or_addition_blocks_old_checkpoint(self):
        restored=restore_bundle(self.bundle(),self.root);self.q.revoke(self.ids[0])
        self.assertEqual(rebuild_plan(restored,current_queue=self.q.path)['status'],'stale_checkpoint')
    def test_lost_current_authority_is_never_assumed_current(self):
        self.q.complete({'source':{'id':self.ids[1]},'sha':'wrong','revision':1,'job':'wrong'})
        restored=restore_bundle(self.bundle(),self.root)
        self.assertIsNone(rebuild_plan(restored)['matches_current_authority'])
        self.assertFalse(rebuild_plan(restored)['automatic_replay_allowed'])
    def test_generation_and_queue_corruption_prevent_restore(self):
        for name in ('original-generation.json','queue'):
            bundle=self.bundle()
            target=bundle/name if name!='queue' else next(bundle.glob('queue-snapshot-*'))/'queue.sqlite3'
            target.write_bytes(b'changed');before=set(self.root.iterdir())
            with self.assertRaises((ValueError,KeyError)):restore_bundle(bundle,self.root)
            self.assertEqual(set(self.root.iterdir()),before)
    def test_missing_generation_is_not_created_during_backup(self):
        (self.bank/'native-generation.json').unlink()
        with self.assertRaises(ValueError):self.bundle()
        self.assertFalse((self.bank/'native-generation.json').exists())
    def test_realm_change_and_parent_symlink_are_rejected(self):
        with self.assertRaises(ValueError):create_bundle(self.bank,self.root,source_realm='household')
        link=self.root/'linked';link.symlink_to(self.bank,target_is_directory=True)
        with self.assertRaises(ValueError):create_bundle(link,self.root,source_realm='fixture')
    def test_interrupted_bundle_has_no_complete_marker(self):
        with patch('tavi.recovery_bundle._json',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.bundle()
        partial=next(self.root.glob('source-recovery-*'))
        self.assertFalse((partial/'manifest.json').exists())
        with self.assertRaises(ValueError):verify_bundle(partial)
    def test_bundle_excludes_spending_profiles_and_native_identity_transfer(self):
        bundle=self.bundle();manifest=verify_bundle(bundle)
        self.assertFalse(manifest['spend_ledger_included']);self.assertFalse(manifest['voice_profiles_included'])
        self.assertFalse(manifest['native_derivatives_included'])
        self.assertEqual({p.name for p in bundle.iterdir()}, {'manifest.json','original-generation.json',manifest['queue_archive']})

    def test_rebuild_comparison_reads_one_consistent_authority_snapshot(self):
        from tavi.recovery_bundle import records
        from experiments.memory.queue_snapshot import _summary
        before=records(self.q.path)
        def concurrent_delete(db):
            result=_summary(db);self.q.revoke(self.ids[0]);return result
        with patch('tavi.recovery_bundle._summary',side_effect=concurrent_delete):
            self.assertEqual(records(self.q.path),before)
        self.assertNotEqual(records(self.q.path),before)
