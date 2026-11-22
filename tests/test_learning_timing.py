import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from experiments.memory.learning_queue import LearningQueue
from experiments.memory.learning_timing import interval


class LearningTimingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'queue.sqlite3'
        self.q = LearningQueue(self.path)
        self.addCleanup(lambda: self.q.close())
        self.scope = {'session_id': 'timing-test', 'task': {
            'actual_speaker_id': 'a', 'audience_ids': ['a'], 'people': {'a': 'Mira'},
            'conversation_at': '2026-10-01T12:00:00Z'}}

    def capture(self, recognition='first'):
        return self.q.capture(self.scope, SimpleNamespace(response_id='unused'),
                              'A fictional private source.', recognition)

    def report(self):
        return self.q.diagnostics()['sources'][0]

    def test_duplicate_restart_preserves_events_without_source_text(self):
        self.capture();job = self.q.claim()
        self.q.note_work(job, 'dispatched');self.q.complete(job)
        before = self.q.diagnostics()
        self.q.close();self.q = LearningQueue(self.path)
        self.assertTrue(self.capture()['duplicate'])
        self.assertFalse(self.q.complete(job))
        self.assertEqual(before, self.q.diagnostics())
        report = self.report()
        self.assertEqual([e['event'] for e in report['events']], ['captured', 'claimed', 'dispatched', 'completed'])
        self.assertEqual(report['capture_to_complete']['basis'], 'same_process_monotonic')
        self.assertNotIn('private source', json.dumps(before))
        self.assertNotIn('Mira', json.dumps(before))

    def test_real_process_reopen_uses_labelled_wall_estimate(self):
        self.capture();self.q.close()
        code = "from experiments.memory.learning_queue import LearningQueue;import sys;q=LearningQueue(sys.argv[1]);j=q.claim();q.note_work(j,'dispatched');q.complete(j);q.close()"
        subprocess.run([sys.executable, '-c', code, str(self.path)], check=True, timeout=10)
        self.q = LearningQueue(self.path)
        report = self.report()
        self.assertEqual(report['capture_to_complete']['basis'], 'cross_process_wall_estimate')
        self.assertEqual(report['attempts'][0]['dispatch_to_outcome']['basis'], 'same_process_monotonic')

    def test_legacy_migration_does_not_fabricate_capture_or_change_source(self):
        sid = self.capture()['source_id'];before = dict(self.q.db.execute('SELECT * FROM learning').fetchone())
        self.q.db.execute('DROP TABLE learning_timing');self.q.db.commit();self.q.close()
        self.q = LearningQueue(self.path)
        self.assertEqual(before, dict(self.q.db.execute('SELECT * FROM learning').fetchone()))
        job = self.q.claim();self.q.complete(job)
        report = self.report()
        self.assertEqual(report['source_id'], sid)
        self.assertEqual(report['timing_coverage'], 'legacy_capture_unknown')
        self.assertIsNone(report['capture_to_complete']['milliseconds'])

    def test_event_write_failure_rolls_back_capture_and_completion(self):
        with patch('experiments.memory.learning_timing.record', side_effect=sqlite3.OperationalError('Disk full')):
            with self.assertRaises(sqlite3.OperationalError):self.capture()
        self.assertEqual(self.q.pending(), 0)
        self.capture();job = self.q.claim()
        with patch('experiments.memory.learning_timing.record', side_effect=sqlite3.OperationalError('Disk full')):
            with self.assertRaises(sqlite3.OperationalError):self.q.complete(job)
        self.assertEqual(self.q.working(), 1)
        self.assertEqual(self.q.sources(), [])
        self.assertTrue(self.q.complete(job))

    def test_recovery_keeps_ambiguous_attempt_and_invalidates_old_owner(self):
        self.capture();old = self.q.claim();self.q.note_work(old, 'dispatched')
        self.q.note_work(old, 'ambiguous');self.q.note_work(old, 'ambiguous')
        self.assertEqual(self.q.working(), 1)
        self.assertTrue(self.q.recover_stopped_job(old))
        new = self.q.claim();self.q.note_work(new, 'dispatched')
        self.assertFalse(self.q.note_work(old, 'dispatched'))
        self.assertFalse(self.q.complete(old));self.assertTrue(self.q.complete(new))
        report = self.report()
        self.assertEqual([a['outcome'] for a in report['attempts']], ['ambiguous', 'completed'])
        self.assertEqual(len([e for e in report['events'] if e['event'] == 'recovered']), 1)

    def test_timing_failure_during_revocation_preserves_epoch_and_original_state(self):
        sid = self.capture()['source_id'];job = self.q.claim()
        with patch('experiments.memory.learning_timing.record', side_effect=sqlite3.OperationalError('Disk full')):
            with self.assertRaises(sqlite3.OperationalError):self.q.revoke(sid)
        self.assertEqual(self.q.generation(), 0)
        self.assertEqual(self.q.working(), 1)
        self.assertTrue(self.q.complete(job))

    def test_revocation_preserves_history_and_blocks_late_dispatch_and_save(self):
        sid = self.capture()['source_id'];job = self.q.claim()
        self.assertTrue(self.q.revoke(sid));self.assertFalse(self.q.revoke(sid))
        self.assertFalse(self.q.note_work(job, 'dispatched'));self.assertFalse(self.q.complete(job))
        report = self.report()
        self.assertEqual(report['state'], 'revoked')
        self.assertEqual(report['attempts'][0]['outcome'], 'revoked')
        self.assertIsNone(report['capture_to_complete']['milliseconds'])

    def test_clock_reversal_and_forward_adjustment_are_not_monotonic_claims(self):
        start = {'clock_domain': 'a', 'wall_ns': 1000000000, 'monotonic_ns': 100}
        same = {'clock_domain': 'a', 'wall_ns': 1, 'monotonic_ns': 200}
        self.assertEqual(interval(start, same)['basis'], 'same_process_monotonic')
        self.assertEqual(interval(start, {**same, 'clock_domain': 'b'})['basis'], 'clock_reversal')
        forward = {**same, 'clock_domain': 'b', 'wall_ns': 1000000000000}
        self.assertEqual(interval(start, forward)['basis'], 'cross_process_wall_estimate')

    def test_diagnostics_limits_and_read_snapshot(self):
        self.capture();self.capture('second')
        result = self.q.diagnostics(limit=1)
        self.assertEqual(result['counts'], {'pending': 2})
        self.assertTrue(result['sources_truncated'])
        self.assertFalse(self.q.db.in_transaction)
        for value in (0, True, 1001, '2'):
            with self.assertRaises(ValueError):self.q.diagnostics(limit=value)

    def test_unknown_and_backlog_rejections_create_no_timing(self):
        self.q.maximum_pending = 0
        self.assertFalse(self.capture()['queued'])
        self.scope['task']['actual_speaker_id'] = 'unknown'
        self.assertFalse(self.capture()['queued'])
        self.assertEqual(self.q.db.execute('SELECT count(*) FROM learning_timing').fetchone()[0], 0)
