import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from experiments.memory.learning_queue import LearningQueue
from experiments.memory.queue_snapshot import snapshot_queue,verify_snapshot,restore_offline,MARKER
from tavi.storage import Store


class QueueSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.path=self.root/'active.sqlite3'
        self.q=LearningQueue(self.path);self.addCleanup(self.q.close)
        scope={'session_id':'snapshot-fiction','task':{'actual_speaker_id':'a','people':{'a':'Mira'},'audience_ids':['a'],'conversation_at':'2026-10-01T12:00:00Z'}}
        def capture(n):return self.q.capture(scope,SimpleNamespace(response_id='unused'),'Fictional source '+str(n),str(n))['source_id']
        self.ids=[capture(1)];self.q.complete(self.q.claim())
        self.ids.append(capture(2));self.job=self.q.claim();self.q.note_work(self.job,'dispatched');self.q.note_work(self.job,'ambiguous')
        self.ids.append(capture(3));self.ids.append(capture(4));self.q.revoke(self.ids[-1])

    def snapshot(self):return snapshot_queue(self.path,self.root)
    def rows(self,path):
        db=sqlite3.connect(Path(path).as_uri()+'?mode=ro',uri=True)
        try:return {table:db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall() for table in ('learning','learning_meta','learning_timing')}
        finally:db.close()

    def test_online_backup_includes_uncheckpointed_wal_and_all_job_states(self):
        self.assertTrue(Path(str(self.path)+'-wal').stat().st_size>0)
        before=self.rows(self.path);archive=self.snapshot()
        self.assertEqual(self.rows(archive/'queue.sqlite3'),before)
        self.assertEqual(verify_snapshot(archive)['summary']['counts'],{'complete':1,'pending':1,'revoked':1,'working':1})
        self.assertEqual(verify_snapshot(archive)['summary']['revocation_epoch'],1)

    def test_offline_restore_preserves_tombstone_and_ambiguity_but_cannot_start_queue(self):
        archive=self.snapshot();restored=restore_offline(archive,self.root)
        self.assertEqual(self.rows(restored/'queue.sqlite3'),self.rows(self.path))
        with self.assertRaisesRegex(ValueError,'Offline restored queue'):LearningQueue(restored/'queue.sqlite3')
        self.assertFalse(json.loads((restored/MARKER).read_text())['automatic_replay_allowed'])
        self.assertEqual(self.q.working(),1);self.assertEqual(len(self.q.sources()),1)

    def test_archives_and_restores_are_new_and_private_not_overwrites(self):
        first=self.snapshot();second=self.snapshot();self.assertNotEqual(first,second)
        restored=restore_offline(first,self.root);again=restore_offline(first,self.root);self.assertNotEqual(restored,again)
        for folder in (first,second,restored,again):
            self.assertEqual(folder.stat().st_mode&0o777,0o700)
            for file in folder.iterdir():self.assertEqual(file.stat().st_mode&0o777,0o600)

    def test_database_corruption_blocks_restore_before_new_destination(self):
        archive=self.snapshot()
        with (archive/'queue.sqlite3').open('ab') as out:out.write(b'changed')
        before=set(self.root.iterdir())
        with self.assertRaises(ValueError):restore_offline(archive,self.root)
        self.assertEqual(set(self.root.iterdir()),before)

    def test_manifest_corruption_and_missing_completion_rejected(self):
        archive=self.snapshot();manifest=archive/'manifest.json';original=manifest.read_text()
        manifest.write_text(original.replace('"revocation_epoch": 1','"revocation_epoch": 0'))
        with self.assertRaises(ValueError):verify_snapshot(archive)
        manifest.write_text(original.replace('"complete": true','"complete": false'))
        with self.assertRaises(ValueError):verify_snapshot(archive)

    def test_unrelated_spend_database_is_not_copied_or_rolled_back(self):
        ledger_path=self.root/'spend.sqlite3';ledger=Store(ledger_path);self.addCleanup(ledger.close)
        ledger.reserve('uncertain',50_000,25_000_000);before=set(self.root.iterdir())
        with self.assertRaises(ValueError):snapshot_queue(ledger_path,self.root)
        self.assertEqual(set(self.root.iterdir()),before);self.assertEqual(ledger.used_micro_usd(),50_000)

    def test_interrupted_snapshot_has_no_completion_manifest_and_is_not_usable(self):
        with patch('experiments.memory.queue_snapshot._json',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.snapshot()
        partial=next(self.root.glob('queue-snapshot-*'))
        self.assertFalse((partial/'manifest.json').exists())
        with self.assertRaises(ValueError):verify_snapshot(partial)
        self.assertEqual(self.q.working(),1)

    def test_interrupted_restore_is_quarantined_before_database_copy(self):
        archive=self.snapshot()
        with patch('experiments.memory.queue_snapshot.shutil.copyfileobj',side_effect=OSError('drive lost')):
            with self.assertRaises(OSError):restore_offline(archive,self.root)
        partial=next(self.root.glob('queue-offline-restore-*'));self.assertTrue((partial/MARKER).is_file())
        self.assertFalse((partial/'restored-manifest.json').exists())
        with self.assertRaises(ValueError):LearningQueue(partial/'queue.sqlite3')

    def test_missing_parent_and_symlinks_do_not_create_internal_lookalikes(self):
        with self.assertRaises(ValueError):snapshot_queue(self.path,self.root/'absent')
        self.assertFalse((self.root/'absent').exists())
        link=self.root/'linked.sqlite3';link.symlink_to(self.path)
        with self.assertRaises(ValueError):snapshot_queue(link,self.root)

    def test_snapshot_point_does_not_change_after_later_revocation(self):
        archive=self.snapshot();before=hashlib.sha256((archive/'queue.sqlite3').read_bytes()).hexdigest()
        self.q.revoke(self.ids[0]);self.assertEqual(self.q.generation(),2)
        self.assertEqual(verify_snapshot(archive)['summary']['revocation_epoch'],1)
        self.assertEqual(hashlib.sha256((archive/'queue.sqlite3').read_bytes()).hexdigest(),before)
        # A stale snapshot is a historical point, never a safe live rollback.
        restored=restore_offline(archive,self.root)
        with self.assertRaises(ValueError):LearningQueue(restored/'queue.sqlite3')
