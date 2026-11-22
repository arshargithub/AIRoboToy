from dataclasses import asdict
from pathlib import Path
import sqlite3
import tempfile
import unittest

from experiments.memory.subject_contract import Claim, admission_digest
from experiments.memory.typed_store import TypedMemoryStore


class TypedStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'memory.sqlite3'
        self.store = TypedMemoryStore(self.path)
        self.people = {'a': 'Ari'}
        self.source = {'id': 's1', 'speaker_id': 'a', 'text': 'I prefer water.',
                       'at': '2026-01-01T00:00:00Z', 'session': 'one', 'audience_ids': ['a']}
        self.query = {'operation': 'preference', 'subject_id': 'a', 'slot': 'drink'}

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def lookup(self):
        return self.store.snapshot(self.people).lookup(self.query, audience=['a'], as_of='2026-02-01T00:00:00Z')

    def complete(self, job):
        source = job['source']
        claim = Claim('s1:0', 's1', 'a', 'drink', 'water', 'preference', 'self', source['text'])
        return self.store.complete(job, [asdict(claim)], {'admissions': {claim.id: admission_digest(claim, source)},
            'decisions': [{'id': claim.id, 'entailed': True, 'reason': 'Fixture'}], 'rejected': {}}, self.people)

    def test_pending_complete_duplicate_and_restart(self):
        self.store.put(self.source)
        self.assertEqual(self.lookup()['status'], 'pending')
        job = self.store.claim_next()
        self.assertTrue(self.complete(job))
        self.assertFalse(self.complete(job))
        self.assertFalse(self.store.put(self.source)['changed'])
        self.assertIsNone(self.store.claim_next())
        self.store.close();self.store = TypedMemoryStore(self.path)
        self.assertEqual(self.lookup()['value'], 'water')

    def test_delete_during_work_rejects_late_completion_and_stale_retry(self):
        self.store.put(self.source);job = self.store.claim_next()
        self.assertTrue(self.store.delete('s1'))
        self.assertFalse(self.complete(job))
        self.assertEqual(self.store.put(self.source)['state'], 'deleted')
        self.assertEqual(self.lookup()['status'], 'unknown')
        self.store.close();self.store = TypedMemoryStore(self.path)
        self.assertEqual(self.lookup()['status'], 'unknown')

    def test_correction_and_cancellation_invalidate_old_tokens(self):
        self.store.put(self.source);old = self.store.claim_next()
        revised = {**self.source, 'text': 'My preferred drink is water.'}
        with self.assertRaises(ValueError):self.store.put(revised)
        self.store.put(revised, correct=True)
        self.assertFalse(self.complete(old))
        job = self.store.claim_next()
        self.assertTrue(self.store.invalidate_job(job['token']))
        self.assertFalse(self.complete(job))
        current = self.store.claim_next()
        self.assertTrue(self.complete(current))
        self.assertEqual(self.lookup()['value'], 'water')

    def test_working_job_survives_restart_until_explicit_reconciliation(self):
        self.store.put(self.source);old = self.store.claim_next()
        self.store.close();self.store = TypedMemoryStore(self.path)
        self.assertIsNone(self.store.claim_next())
        self.assertEqual(self.lookup()['status'], 'pending')
        self.assertTrue(self.store.invalidate_job(old['token']))
        replacement = self.store.claim_next()
        self.assertFalse(self.complete(old))
        self.assertTrue(self.complete(replacement))

    def test_forged_admission_and_foreign_database_rejected(self):
        self.store.put(self.source);job = self.store.claim_next()
        with self.assertRaises(ValueError):
            self.store.complete(job, [], {'admissions': {'fake': 'digest'}, 'decisions': [], 'rejected': {}}, self.people)
        self.assertEqual(self.lookup()['status'], 'pending')
        foreign = Path(self.temp.name)/'foreign.sqlite3'
        db = sqlite3.connect(foreign);db.execute('CREATE TABLE unrelated (x)');db.close()
        with self.assertRaises(ValueError):TypedMemoryStore(foreign)

    def test_full_sync_and_wal_are_actual_runtime_settings(self):
        self.assertEqual(self.store.db.execute('PRAGMA synchronous').fetchone()[0], 2)
        self.assertEqual(self.store.db.execute('PRAGMA journal_mode').fetchone()[0], 'wal')


if __name__ == '__main__':
    unittest.main()
