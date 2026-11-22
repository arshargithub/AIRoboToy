"""Mounted-SSD fictional offline archive/copy proof; no native activation."""
import io
import json
from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace
import unittest
from experiments.memory.runtime import ROOT,SSD,require_ssd
from experiments.memory.learning_queue import LearningQueue
from experiments.memory.queue_snapshot import snapshot_queue,verify_snapshot,restore_offline
from tavi.experiment_workflow import begin,audit,finish
from tavi.storage import Store


def rows(path):
    db=sqlite3.connect(Path(path).as_uri()+'?mode=ro',uri=True)
    try:return {t:db.execute('SELECT * FROM '+t+' ORDER BY rowid').fetchall() for t in ('learning','learning_meta','learning_timing')}
    finally:db.close()


def run():
    require_ssd();folder,plan=begin(ROOT/'experiments/memory/queue-snapshot-protocol-v1.json',run_root=SSD/'runs/scored')
    print(json.dumps(audit(folder)),flush=True)
    cfg=json.loads((ROOT/'experiments/memory/queue-snapshot-input-v1.json').read_text())
    ledger=Store(ROOT/'.tavi/simulation/simulation.sqlite3');initial=ledger.used_micro_usd()
    q=LearningQueue(folder/'source.sqlite3');errors=[];data={};start=time.monotonic()
    try:
        scope={'session_id':'offline-snapshot-fixture','task':{'actual_speaker_id':'a','people':cfg['people'],'audience_ids':['a'],'conversation_at':cfg['at']}}
        def capture(n):return q.capture(scope,SimpleNamespace(response_id='unused'),cfg['text'],str(n))['source_id']
        capture(1);q.complete(q.claim());capture(2);job=q.claim();q.note_work(job,'dispatched');q.note_work(job,'ambiguous')
        capture(3);q.revoke(capture(4))
        before=rows(q.path);archive=snapshot_queue(q.path,folder);verified=verify_snapshot(archive);restored=restore_offline(archive,folder)
        data={'fixture_sources':sum(verified['summary']['counts'].values()),'archive_restore_states_equal':before==rows(archive/'queue.sqlite3')==rows(restored/'queue.sqlite3'),
              'revocation_epoch_preserved':verified['summary']['revocation_epoch']==q.generation()==1,
              'ambiguous_claim_preserved':verified['summary']['counts'].get('working')==1,'live_queue_open_blocked':False,
              'summary':verified['summary'],'archive':str(archive),'restored':str(restored)}
        try:
            unsafe=LearningQueue(restored/'queue.sqlite3');unsafe.close()
        except ValueError:data['live_queue_open_blocked']=True
    except Exception as error:errors.append(type(error).__name__+': '+str(error))
    finally:q.close()
    stream=io.StringIO();tests=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromName(cfg['controlled_tests']))
    (folder/'controlled-tests.txt').write_text(stream.getvalue())
    if time.monotonic()-start>plan['limits']['maximum_wall_seconds']:errors.append('wall_limit')
    metrics={k:data.get(k) for k in ('fixture_sources','archive_restore_states_equal','revocation_epoch_preserved','ambiguous_claim_preserved','live_queue_open_blocked')}
    metrics.update(controlled_checks_passed=tests.testsRun-len(tests.errors)-len(tests.failures),test_failures=len(tests.errors)+len(tests.failures),collection_errors=len(errors),additional_api_usd=(ledger.used_micro_usd()-initial)/1e6)
    ledger.close();(folder/'observations.json').write_text(json.dumps({'metrics':metrics,'data':data,'errors':errors,'native_activation':False},indent=2)+'\n')
    artifacts=[p for p in folder.rglob('*') if p.is_file() and p.name not in ('run.json','protocol.json') and 'source' not in p.relative_to(folder).parts and 'context' not in p.relative_to(folder).parts]
    sealed=finish(folder,metrics,artifacts=artifacts,completed=not errors,error=';'.join(errors) or None)
    report={'run':str(folder),'metrics':metrics,'decision':sealed['decision'],'audit':audit(folder),'critical_review':[
        'Online SQLite backup includes committed WAL pages and a consistent four-source point while original connection remains open. Not a native/Postgres bank, audio, embedding profile or global spend backup.',
        'Both complete/pending/ambiguous-working/revoked states, revocation epoch and timing rows survive exact archive/copy comparison. A restored queue is marked offline before DBcopy and ordinary LearningQueue refuses it; no activation/reconciliation/rebuild feature is implemented.',
        'Ten local controls cover checksum/summary/completion corruption, partial write/copy, permissions, symlinks, unrelated spend-store exclusion and historical snapshot revocations. Injected faults are not actual drive removal, power failure or sustained concurrent-native recovery.',
        'Historical snapshot can predate later revocations and uncertain native completion. Never replay or connect old derivatives from this copy without reconciliation and current revocation/source state; no spending ledger rollback is possible through this primitive.',
        'Plaintext private local files700/600, fixed schema and content hashes. These are integrity checks, not encryption or cryptographic authenticity against a malicious file editor; no data leaves the external drive.',
        'Actual trial uses fictional text only. No human memory backup, native activation, cloud/paid request or productE6restore acceptance. Earlier archives and active databases are never replaced.'
    ]}
    (ROOT/'docs/evaluations/paprika_queue_offline_restore_01.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)


if __name__=='__main__':run()
