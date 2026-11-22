import asyncio
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from experiments.memory.worker_transport import WorkerTransport, MemoryWorkerTimeout, MemoryWorkerUnavailable
from experiments.memory.learning_queue import LearningQueue
from experiments.memory.learning_supervisor import LearningSupervisor

FIXTURE = Path(__file__).parent/'fixtures/memory_transport_worker.py'


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name);self.workers = []

    def worker(self):
        index = len(self.workers);audit = self.folder/f'calls-{index}.jsonl'
        process = subprocess.Popen([sys.executable, str(FIXTURE), str(audit)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        worker = WorkerTransport(process, (self.folder/f'worker-{index}.log').open('a'), 'controlled')
        self.workers.append(worker);self.addCleanup(worker.stop)
        worker.audit_path = audit
        worker.send({'op': 'initialize'}, timeout=3)
        return worker

    def calls(self, worker):
        return [json.loads(line) for line in worker.audit_path.read_text().splitlines()]

    def test_normal_serial_calls_and_acknowledged_application_error(self):
        w = self.worker()
        self.assertEqual(w.send({'op': 'query', 'marker': 'one'})['result']['marker'], 'one')
        self.assertFalse(w.send({'op': 'application_error'})['ok'])
        self.assertEqual(w.send({'op': 'query', 'marker': 'two'})['result']['marker'], 'two')
        self.assertFalse(w.unusable)

    def test_timeout_reaps_child_and_refuses_late_answer_reuse_without_retry(self):
        w = self.worker();start = time.monotonic()
        with self.assertRaises(MemoryWorkerTimeout):
            w.send({'op': 'sleep', 'seconds': 5, 'marker': 'old'}, timeout=.03)
        self.assertLess(time.monotonic()-start, 1)
        self.assertIsNotNone(w.process.poll());self.assertTrue(w.unusable)
        w.buffer = b'{"ok":true,"result":{"marker":"old"}}\n'
        with self.assertRaises(MemoryWorkerUnavailable):w.send({'op': 'query', 'marker': 'new'})
        self.assertEqual([c['op'] for c in self.calls(w)], ['initialize', 'sleep'])
        w.stop();w.stop()
        self.assertTrue(w.log.closed);self.assertTrue(w.process.stdout.closed)

    def test_eof_and_malformed_envelope_retire_only_owned_child(self):
        survivor = self.worker()
        for request in ({'op': 'exit', 'code': 3}, {'op': 'malformed'}):
            w = self.worker()
            with self.assertRaises(MemoryWorkerUnavailable):w.send(request, timeout=1)
            self.assertIsNotNone(w.process.poll());self.assertTrue(w.unusable)
            with self.assertRaises(MemoryWorkerUnavailable):w.send({'op': 'query'})
        self.assertEqual(survivor.send({'op': 'query', 'marker': 'alive'})['result']['marker'], 'alive')

    def test_expected_injected_exit78_is_recorded_but_cannot_reuse_child(self):
        w = self.worker()
        value = w.send({'op': 'exit', 'code': 78, 'crash': 'after ledger'}, expect_crash=True)
        self.assertEqual(value['result'], {'injected_exit': 78, 'boundary': 'after ledger'})
        with self.assertRaises(MemoryWorkerUnavailable):w.send({'op': 'query'})

    def test_logs_and_invalid_local_arguments_do_not_poison_healthy_channel(self):
        w = self.worker();before = len(self.calls(w))
        for timeout in (0, -1, True, float('nan'), float('inf'), '1'):
            with self.assertRaises(ValueError):w.send({'op': 'query'}, timeout=timeout)
        with self.assertRaises(TypeError):w.send({'op': object()})
        self.assertEqual(len(self.calls(w)), before)
        self.assertEqual(w.send({'op': 'logs', 'marker': 'healthy'})['result']['marker'], 'healthy')
        self.assertIn('Fixture boot log', (self.folder/'worker-0.log').read_text())

    def test_concurrent_call_is_refused_without_dispatch_or_poisoning_owner(self):
        w = self.worker()
        with concurrent.futures.ThreadPoolExecutor(1) as pool:
            first = pool.submit(w.send, {'op': 'sleep', 'seconds': .15, 'marker': 'owned'}, 2)
            deadline = time.monotonic()+1
            while len(self.calls(w)) < 2:
                if time.monotonic() > deadline:self.fail('Owned request did not dispatch')
                time.sleep(.002)
            with self.assertRaises(RuntimeError):w.send({'op': 'query', 'marker': 'interleaved'})
            self.assertEqual(first.result(timeout=2)['result']['marker'], 'owned')
        self.assertEqual(len(self.calls(w)), 2)
        self.assertFalse(w.unusable)

    def test_existing_process_class_uses_qualified_transport(self):
        from experiments.memory.pilot import Process
        process = subprocess.Popen([sys.executable, str(FIXTURE), str(self.folder/'wrapped-calls.jsonl')],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        with patch('experiments.memory.pilot.subprocess.Popen', return_value=process), patch('experiments.memory.pilot.engine_environment', return_value={}):
            w = Process('hindsight', self.folder, self.folder)
        self.addCleanup(w.stop)
        self.assertEqual(w.send({'op': 'initialize', 'marker': 'wrapped'}, timeout=3)['result']['marker'], 'wrapped')
        with self.assertRaises(MemoryWorkerTimeout):w.send({'op': 'sleep', 'seconds': 5}, timeout=.03)
        with self.assertRaises(MemoryWorkerUnavailable):w.send({'op': 'query'})

    def test_timed_out_ingest_remains_ambiguous_and_restart_does_not_retry(self):
        w = self.worker();path = self.folder/'queue.sqlite3';q = LearningQueue(path);self.addCleanup(q.close)
        scope = {'session_id': 'transport', 'task': {'actual_speaker_id': 'a', 'audience_ids': ['a'],
                 'people': {'a': 'Mira'}, 'conversation_at': '2026-10-01T12:00:00Z'}}
        q.capture(scope, SimpleNamespace(response_id='unused'), 'A fictional hobby.', 'one')
        class Client:
            def initialize(self):pass
            def ingest(self, source):return w.send({'op': 'sleep', 'seconds': 5}, timeout=.03)
            def close(self):w.stop()
            def abort(self):w.process.kill() if w.process.poll() is None else None
        s = LearningSupervisor(path, Client);self.addCleanup(s.stop);s.start()
        deadline = time.monotonic()+3
        while s.snapshot()['status'] != 'needs_reconciliation':
            if time.monotonic() > deadline:self.fail('Ambiguous work not retained')
            time.sleep(.002)
        s.stop();self.assertEqual(q.working(), 1);self.assertEqual(q.sources(), [])
        self.assertEqual(q.diagnostics()['sources'][0]['attempts'][0]['outcome'], 'ambiguous')
        factories = []
        second = LearningSupervisor(path, lambda: factories.append(True));self.addCleanup(second.stop);second.start()
        deadline = time.monotonic()+3
        while second.snapshot()['status'] != 'needs_reconciliation':
            if time.monotonic() > deadline:self.fail('Restart did not block ambiguity')
            time.sleep(.002)
        second.stop();self.assertEqual(factories, [])
        self.assertEqual([c['op'] for c in self.calls(w)], ['initialize', 'sleep'])


class ControllerOutageTests(unittest.IsolatedAsyncioTestCase):
    async def test_lookup_timeout_never_generates_or_plays_a_guessed_answer(self):
        from experiments.memory.conversation_adapter import MemoryTextProvider
        from tavi.chunked_conversation import ChunkedConversation
        from tavi.conversation_providers import Speech
        from tavi.storage import Store
        calls = [];voiced = [];refs = []
        scope = {'revision': 1, 'task': {'actual_speaker_id': 'a', 'audience_ids': ['a'], 'people': {'a': 'Mira'}}}
        class Reference:
            def __init__(self, store):self.closed = False;refs.append(self)
            async def connect(self):pass
            async def reply(self, *args):calls.append(True);return {'text': 'An invented memory.', 'status': 'completed'}
            async def close(self):self.closed = True
        class Voice:
            async def synthesize(self, text):voiced.append(text);return Speech(b'controlled', 100)
        async def recall(task):raise MemoryWorkerTimeout('controlled lookup timeout')
        store = Store();self.addCleanup(store.close)
        provider = MemoryTextProvider(store, scope=lambda: scope, recall=recall, reference_factory=Reference)
        c = ChunkedConversation(store, provider=provider, speech=Voice(), context_revision=lambda: scope)
        self.addAsyncCleanup(c.close);c.start('test')
        def request(text, number):
            c.feed('test', {'events': [{'type': 'speech_started', 'utterance': number},
                {'type': 'recognition', 'utterance': number, 'text': text, 'final': True}]})
        request('Paprika, what hobby do I like?', 1)
        for _ in range(60):await asyncio.sleep(0)
        self.assertEqual(c.failure['code'], 'memory_worker_unavailable')
        self.assertEqual(c.controller.error, 'Memory is unavailable')
        self.assertIn('Stop and save', c.notice)
        self.assertIsNone(c.audio);self.assertEqual(calls, []);self.assertEqual(voiced, [])
        self.assertFalse(any(m['role'] == 'assistant' for m in c.history))
        self.assertTrue(refs[0].closed)
        request('Paprika, goodbye.', 2)
        for _ in range(60):await asyncio.sleep(0)
        self.assertIsNone(c.failure);self.assertIsNotNone(c.audio)
        self.assertIn('Bye for now', c.audio['text']);self.assertEqual(calls, [])
