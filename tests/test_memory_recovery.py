import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from experiments.memory.recovery import Journal
from experiments.memory.qualification_worker import Coordinator
from experiments.memory.context_envelope import pack


class Encoding:
    def encode(self,s):return s.encode()


def episode(sid='e1',audience=None):
    return {'id':sid,'speaker_id':'p1','audience_ids':audience or ['p1','p2'],
            'session':'s1','at':'2026-01-01','text':'A significant fictional event.'}


class JournalTests(unittest.TestCase):
    def test_crash_reopen_does_not_publish_an_ambiguous_native_write(self):
        with tempfile.TemporaryDirectory() as directory:
            j=Journal(directory);intent=j.prepare(episode());g=j.generation(intent['scope'])[0];j.close()
            j=Journal(directory)
            with self.assertRaisesRegex(RuntimeError,'quarantined'):j.readable(['p1'])
            self.assertTrue(j.prepare(episode())['duplicate'])
            j.publish(intent['scope'],'fresh-generation')
            self.assertEqual(j.readable(['p1']),[('p1-p2','fresh-generation')]);j.close()

    def test_tombstone_survives_crash_and_stale_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            j=Journal(directory);j.prepare(episode());j.publish('p1-p2','first')
            j.tombstone('e1');j.close();j=Journal(directory)
            self.assertEqual(j.sources(),[])
            self.assertTrue(j.prepare(episode())['deleted'])
            with self.assertRaises(RuntimeError):j.readable(['p1','p2'])
            j.publish('p1-p2','empty-rebuilt');self.assertEqual(j.sources(),[]);j.close()

    def test_quarantine_is_scoped_but_never_partially_answers_affected_audience(self):
        with tempfile.TemporaryDirectory() as directory:
            j=Journal(directory);j.prepare(episode(audience=['p1']));j.publish('p1','private')
            j.prepare(episode('e2',['p2']))
            self.assertEqual(j.readable(['p1']),[('p1','private')])
            self.assertEqual(j.readable(['p1','p2']),[])
            with self.assertRaises(RuntimeError):j.readable(['p2'])
            j.close()

    def test_unmapped_native_dependency_cannot_be_hidden_by_known_source(self):
        native=[{'fact':'unsafe partial provenance','source_ids':['e1'], 'episodes':['known','missing'],
                 'unresolved_native_sources':['missing']}]
        result=pack('graphiti',native,[episode()],['p1'],Encoding())
        self.assertEqual(result['selected_facts'],0)

    def test_hindsight_partial_support_is_rejected(self):
        native=[{'results':[{'id':'obs','text':'A combined observation','tags':['source:e1'],
                            'source_fact_ids':['missing']}],'source_facts':{}}]
        self.assertEqual(pack('hindsight',native,[episode()],['p1'],Encoding())['selected_facts'],0)


class CoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_rebuild_keeps_tombstone_and_quarantine(self):
        with tempfile.TemporaryDirectory() as directory:
            c=Coordinator.__new__(Coordinator);c.journal=Journal(directory);c.workers={};c.engine='sqlite'
            c.journal.prepare(episode());c.journal.publish('p1-p2','old')
            class FailingWorker:
                async def ingest(self,*args):raise RuntimeError('interrupted native write')
            async def worker(*args):return FailingWorker()
            c.worker=worker
            c.journal.prepare(episode('e2'));c.journal.publish('p1-p2','old')
            with self.assertRaisesRegex(RuntimeError,'interrupted'):
                await c.delete('e1',{'p1':'Morgan'})
            self.assertEqual([e['id'] for e in c.journal.sources()],['e2'])
            with self.assertRaisesRegex(RuntimeError,'quarantined'):c.journal.readable(['p1'])
            c.journal.close()

    async def test_recovery_never_replays_deleted_source_and_publishes_last(self):
        with tempfile.TemporaryDirectory() as directory:
            c=Coordinator.__new__(Coordinator);c.journal=Journal(directory);c.workers={};c.engine='sqlite'
            c.journal.prepare(episode());c.journal.publish('p1-p2','old')
            c.journal.prepare(episode('e2'));c.journal.tombstone('e1')
            replay=[]
            class Worker:
                async def ingest(self,e,people):
                    self_test.assertEqual(c.journal.pending(),['p1-p2'])
                    replay.append(e['id']);return {'stored':True}
            self_test=self
            async def worker(*args):return Worker()
            c.worker=worker
            await c.recover({})
            self.assertEqual(replay,['e2']);self.assertEqual(c.journal.pending(),[])
            self.assertNotEqual(c.journal.readable(['p1'])[0][1],'old');c.journal.close()
