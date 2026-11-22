"""Bounded zero-inference external-drive persistence and stale-job checks."""
from copy import deepcopy
from dataclasses import asdict
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from experiments.memory.runtime import ROOT, SSD, require_ssd
from experiments.memory.subject_contract import Claim, admission_digest
from experiments.memory.typed_store import TypedMemoryStore
from tavi.experiment_workflow import begin, finish, audit


def publish(store, job, saved):
    source = job['source']
    proposals, admissions = [], {}
    # Rebind fixture identifiers only for lifecycle probes; source meaning is
    # unchanged and no model or new semantic inference occurs.
    for index, old in enumerate(saved['proposals']):
        claim = Claim(**{**old, 'id': source['id'] + ':' + str(index), 'source_id': source['id']})
        proposals.append(asdict(claim))
        if old['id'] in saved['validation']['admissions']:
            admissions[claim.id] = admission_digest(claim, source)
    validation = deepcopy(saved['validation'])
    validation['admissions'] = admissions
    return store.complete(job, proposals, validation, PEOPLE)


def query(store, subject='p1', slot='drink', audience=None, at='2026-05-01T00:00:00Z'):
    return store.snapshot(PEOPLE).lookup({'operation': 'preference', 'subject_id': subject, 'slot': slot},
                                       audience=audience or [subject], as_of=at)


def crash_child(folder):
    fixture = json.loads((ROOT/'experiments/memory/claim-admission-input-v1.json').read_text())
    source = next(s for s in fixture['sources'] if s['id'] == 'n003')
    store = TypedMemoryStore(folder/'crash.sqlite3')
    store.put(source)
    job = store.claim_next()
    with (folder/'crashed-job.json').open('w') as stream:
        json.dump(job, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os._exit(78)


def run():
    global PEOPLE
    require_ssd()
    folder, plan = begin(ROOT/'experiments/memory/typed-store-protocol-v1.json', run_root=SSD/'runs/scored')
    print(json.dumps({'run': str(folder), 'preflight': audit(folder)}), flush=True)
    fixture = json.loads((ROOT/plan['configuration']['input']).read_text())
    PEOPLE = fixture['people']
    sources = {s['id']: s for s in fixture['sources']}
    saved = {r['source_id']: r for r in json.loads(open(plan['configuration']['admissions']).read())['sources']}
    metrics = {'sources_committed': 0, 'collection_errors': 0, 'additional_api_usd': 0}
    observations, stores = {}, []
    try:
        store = TypedMemoryStore(folder/'main.sqlite3');stores.append(store)
        metrics['wal_full_verified'] = (store.db.execute('PRAGMA synchronous').fetchone()[0] == 2
            and store.db.execute('PRAGMA journal_mode').fetchone()[0] == 'wal')
        for source in sources.values():store.put(source)
        while job := store.claim_next():
            if not publish(store, job, saved[job['source']['id']]):raise ValueError('Initial publication failed')
            metrics['sources_committed'] += 1
        original = store.snapshot(PEOPLE).revision
        store.close();stores.remove(store)
        store = TypedMemoryStore(folder/'main.sqlite3');stores.append(store)
        metrics['restart_snapshot_identical'] = store.snapshot(PEOPLE).revision == original
        metrics['duplicates_do_not_requeue'] = all(not store.put(source)['changed'] for source in sources.values()) and store.claim_next() is None
        metrics['private_scope_preserved'] = (query(store,'p2','game')['value'] == 'Azul'
            and query(store,'p2','game',['p2','p3'])['status'] == 'unknown')
        store.delete('n031')
        store.close();stores.remove(store)
        store = TypedMemoryStore(folder/'main.sqlite3');stores.append(store)
        metrics['deletion_survives_restart'] = (query(store,'p1','game')['status'] == 'unknown'
            and store.put(sources['n031'])['state'] == 'deleted')
        probe = TypedMemoryStore(folder/'late.sqlite3');stores.append(probe)
        probe.put(sources['n003']);old = probe.claim_next();probe.delete('n003')
        metrics['late_delete_completion_rejected'] = not publish(probe,old,saved['n003'])
        correction = TypedMemoryStore(folder/'correct.sqlite3');stores.append(correction)
        correction.put(sources['n003']);old = correction.claim_next()
        replacement = {**sources['n005'], 'id': 'n003'}
        correction.put(replacement, correct=True)
        metrics['late_corrected_completion_rejected'] = not publish(correction,old,saved['n003'])
        current = correction.claim_next();correction.invalidate_job(current['token'])
        metrics['cancelled_completion_rejected'] = not publish(correction,current,saved['n005'])
        latest = correction.claim_next()
        if not publish(correction,latest,saved['n005']):raise ValueError('Corrected source publication failed')
        child = subprocess.run([sys.executable, '-m', 'experiments.memory.typed_store_trial', '--crash-child', str(folder)],
                               cwd=ROOT, capture_output=True, text=True, timeout=25)
        metrics['child_exit_code'] = child.returncode
        observations['child_stderr'] = child.stderr
        crashed = json.loads((folder/'crashed-job.json').read_text())
        recovery = TypedMemoryStore(folder/'crash.sqlite3');stores.append(recovery)
        metrics['crashed_job_read_pending'] = query(recovery)['status'] == 'pending' and recovery.claim_next() is None
        if not recovery.invalidate_job(crashed['token']):raise ValueError('Known-stopped job reconciliation failed')
        retry = recovery.claim_next()
        metrics['reconciled_job_committed'] = (not publish(recovery,crashed,saved['n003'])
            and publish(recovery,retry,saved['n003']) and query(recovery)['value'] == 'rooibos')
        observations['reconciled_answer'] = query(recovery)
        observations['sqlite_version'] = sqlite3.sqlite_version
    except Exception as exc:
        metrics['collection_errors'] = 1
        observations['error'] = type(exc).__name__ + ': ' + str(exc)
    finally:
        for store in stores:
            store.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            store.close()
    review = {'run': str(folder), 'metrics': metrics, 'critical_review': [
        'New isolated SSD databases only; input facts/admissions were already reviewed development evidence. No model requests.',
        'Child exits after committed canonical source/job claim, before completing inference. This is one known process-loss boundary, not arbitrary transaction/power-loss or native-engine durability.',
        'FULL/WAL observed on this SQLite runtime; a short successful run cannot prove storage hardware reliability. No drive unplug is attempted.',
        'Tombstones prevent query/resurrection but historical source/version rows and fixture artifacts remain. This is not physical erasure.',
        'One explicit cancelled token is reconciled; no assumption that every background worker is dead.',
        'Lifecycle probes mechanically rebind already-supported fixture identifiers; this does not add automatic extraction or full E5 acceptance.']}
    (folder/'observations.json').write_text(json.dumps(observations, indent=2))
    (folder/'critical-review.json').write_text(json.dumps(review, indent=2))
    artifacts = [folder/'observations.json', folder/'critical-review.json', *folder.glob('*.sqlite3'), *folder.glob('*job.json')]
    result = finish(folder, metrics, artifacts=artifacts, completed=not metrics['collection_errors'], error=observations.get('error'))
    review.update(outcome=result['decision']['outcome'], audit=audit(folder))
    (ROOT/'docs/evaluations/paprika_memory_typed_store_01.json').write_text(json.dumps(review, indent=2))
    print(json.dumps(review, indent=2))


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--crash-child':
        crash_child(Path(sys.argv[2]))
    else:
        run()
