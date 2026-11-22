"""Zero-paid durable timing screen with controlled workers, no audio/model."""
import asyncio
import io
import json
import math
import threading
import time
import unittest
from types import SimpleNamespace

from experiments.memory.learning_queue import LearningQueue, LearningConversation
from experiments.memory.learning_supervisor import LearningSupervisor
from experiments.memory.runtime import ROOT, SSD, require_ssd
from tavi.conversation_providers import Speech
from tavi.experiment_workflow import begin, audit, finish
from tavi.storage import Store


async def run():
    require_ssd()
    folder, plan = begin(ROOT/'experiments/memory/timing-protocol-v1.json', run_root=SSD/'runs/scored')
    print(json.dumps(audit(folder)), flush=True)
    cfg = json.loads((ROOT/'experiments/memory/timing-input-v1.json').read_text())
    ledger = Store(ROOT/'.tavi/simulation/simulation.sqlite3')
    initial = ledger.used_micro_usd()
    store = Store()
    q = LearningQueue(folder/'queue.sqlite3')
    scope = {'session_id': 'timing-fixture', 'task': {
        'actual_speaker_id': 'a', 'people': {'a': 'Mira'}, 'audience_ids': ['a'],
        'conversation_at': '2026-10-01T12:00:00Z'}}
    gate = threading.Event()
    entered = threading.Event()

    class Client:
        def initialize(self):pass
        def ingest(self, source):
            entered.set()
            if not gate.wait(5):raise TimeoutError('Controlled gate')
            time.sleep(.002)
            return {'controlled': True}
        def abort(self):gate.set()
        def close(self):pass

    class Provider:
        async def stream_reply(self, history):yield 'That sounds fun.'
        async def close(self):pass

    class Voice:
        async def synthesize(self, text):return Speech(b'not-played', 100)

    s = LearningSupervisor(q.path, Client, maximum_jobs=128)
    s.start()
    c = LearningConversation(store, provider=Provider(), speech=Voice(), context_revision=lambda: scope,
                             learning_queue=q, learning_notify=s.notify)
    c.start('controlled')
    result = {'errors': [], 'capture_ms': [], 'heartbeat_delay_ms': [], 'restart_preservation_checks': 0,
              'real_native_inference': False, 'microphone': False, 'playback': False}
    deadline = time.monotonic() + plan['limits']['maximum_wall_seconds']
    done = False

    async def wait(fn):
        async with asyncio.timeout(min(5, max(0, deadline-time.monotonic()))):
            while not fn():await asyncio.sleep(.002)

    async def beat():
        while not done:
            start = time.monotonic()
            await asyncio.sleep(.005)
            result['heartbeat_delay_ms'].append(max(0, (time.monotonic()-start-.005)*1000))

    async def reopen():
        nonlocal q, s
        await wait(lambda: q.pending() == 0)
        await asyncio.to_thread(s.stop, abort=False)
        before = q.diagnostics(limit=1000)
        path = q.path
        q.close();q = LearningQueue(path)
        if q.diagnostics(limit=1000) != before:raise ValueError('Restart changed durable timing')
        result['restart_preservation_checks'] += 1
        s = LearningSupervisor(path, Client, maximum_jobs=128)
        s.start()
        c.learning_queue = q;c.learning_notify = s.notify

    heartbeat = asyncio.create_task(beat())
    try:
        c.feed('controlled', {'events': [{'type': 'speech_started', 'utterance': 1},
               {'type': 'recognition', 'utterance': 1, 'text': cfg['text'], 'recognition_id': 'initial', 'final': True}]})
        await wait(lambda: c.audio is not None and entered.is_set())
        result['reply_ready_while_save_blocked'] = not gate.is_set() and not q.sources()
        gate.set()
        for n in range(1, cfg['sources']):
            if n == 64:await reopen()
            await wait(lambda: q.pending() < 8)
            start = time.monotonic()
            event = q.capture(scope, SimpleNamespace(response_id='unused'), cfg['text'], 'recognition-'+str(n))
            result['capture_ms'].append((time.monotonic()-start)*1000)
            if not event['queued']:raise ValueError('Unexpected rejected capture')
            s.notify()
            await asyncio.sleep(.002)
        await reopen()
        result['diagnostics'] = q.diagnostics(limit=1000)
        result['completed_sources'] = len(q.sources())
        for row in result['diagnostics']['sources']:
            if [e['event'] for e in row['events']] != ['captured', 'claimed', 'dispatched', 'completed']:
                raise ValueError('Missing or duplicated transition')
    except Exception as error:
        result['errors'].append(type(error).__name__+': '+str(error))
    finally:
        gate.set()
        await c.close()
        await asyncio.to_thread(s.stop)
        q.close();store.close()
        done = True
        await heartbeat
    suite = unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromName(name) for name in
                               ('tests.test_learning_timing', 'tests.test_learning_supervisor')])
    stream = io.StringIO()
    tests = await asyncio.to_thread(unittest.TextTestRunner(stream=stream).run, suite)
    (folder/'controlled-tests.txt').write_text(stream.getvalue())
    def p95(values):return sorted(values)[math.ceil(.95*len(values))-1] if values else None
    metrics = {'completed_sources': result.get('completed_sources'),
               'durable_transition_events': sum(len(r['events']) for r in result.get('diagnostics', {}).get('sources', [])),
               'restart_preservation_checks': result['restart_preservation_checks'],
               'reply_ready_while_save_blocked': result.get('reply_ready_while_save_blocked'),
               'invariant_checks_passed': tests.testsRun-len(tests.failures)-len(tests.errors),
               'collection_errors': len(result['errors']),
               'capture_p95_ms': p95(result['capture_ms']), 'capture_max_ms': max(result['capture_ms'], default=None),
               'heartbeat_p95_delay_ms': p95(result['heartbeat_delay_ms']),
               'heartbeat_max_delay_ms': max(result['heartbeat_delay_ms'], default=None),
               'additional_api_usd': (ledger.used_micro_usd()-initial)/1e6}
    ledger.close()
    result['metrics'] = metrics
    (folder/'observations.json').write_text(json.dumps(result, indent=2)+'\n')
    sealed = finish(folder, metrics, artifacts=[folder/'observations.json', folder/'queue.sqlite3', folder/'controlled-tests.txt'],
                    completed=not result['errors'], error='; '.join(result['errors']) or None)
    report = {'run': str(folder), 'metrics': metrics, 'decision': sealed['decision'], 'audit': audit(folder),
              'critical_review': [
                  'Controlled2ms worker and fake voice/reply measure scheduling/durable bookkeeping only; not Hindsight/K/ASR/E3/E5 latency.',
                  '128sources/512transitions persist across two queue/supervisor reopens in one run. A separate real-process test verifies cross-process interval labels, not OS reboot or drive-removal endurance.',
                  'Ten new timing invariants plus eight existing supervisor/controller faults check migration, transaction rollback, duplicate/recovery/revocation and explicit ambiguity. No paid retry or threshold change.',
                  'Within-process intervals use monotonic clock. Cross-process wall estimates include downtime and may include forward clock changes; observed reversal yields unknown, never a negative latency.',
                  'Timing metadata contains source/job IDs, event names and clock readings, no duplicated source text/person/audience. It stays in the same private local queue; not an anonymization or secure-erasure claim.',
                  'Legacy records are not backfilled; prior sealed human-pilot timing remains incomplete. No family accuracy, engine selection or human acceptance granted.',
                  'Capture timestamps are taken within the atomic capture transaction, before its commit; capture timing benchmark separately includes commit cost. Dispatch-to-outcome includes local transport/acknowledgement and unresolved outcomes stay explicit.'
              ]}
    (ROOT/'docs/evaluations/paprika_memory_durable_timing_01.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':asyncio.run(run())
