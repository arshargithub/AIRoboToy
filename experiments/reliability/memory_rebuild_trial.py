"""Bounded native-index rebuild from a verified fictional source checkpoint.

Offline staging only. No source rollback, real family data, response generation
or automatic live adoption. This is recovery evidence, not another quality sweep.
"""
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import time

from experiments.memory.household_model_trial import wait_native_readiness
from experiments.memory.household_restart_trial import readonly_view
from experiments.memory.learning_gateway import LearningGateway
from experiments.memory.learning_queue import LearningQueue
from experiments.memory.pilot import Process
from experiments.memory.runtime import ROOT, SSD, require_ssd, MODEL, MODEL_RATES
from tavi.experiment_workflow import begin,finish,audit,discover_runs,read_protocol,digest
from tavi.household_memory import HouseholdMemory
from tavi.memory_generation import native_directory
from tavi.memory_projection import projection_report
from tavi.recovery_bundle import create_bundle,restore_bundle,rebuild_plan,verify_bundle
from tavi.storage import Store, APPROVED_BUDGET_MICRO_USD
from experiments.reliability.mac_reliability_trial import status


def read_queue(path):
    q=LearningQueue.__new__(LearningQueue);q.path=path
    q.db=sqlite3.connect(Path(path).as_uri()+'?mode=ro',uri=True);q.db.row_factory=sqlite3.Row
    return q


def send(worker,body):
    result=worker.send(body,timeout=90)
    if not result['ok']:raise RuntimeError('Native rebuild operation failed; do not retry an uncertain write')
    return result['result']


async def collect(folder,plan,ledger):
    source=Path(plan['configuration']['original_fixture']);people=json.loads((ROOT/'experiments/memory/household-model-input-v1.json').read_text())['people']
    result={'model_replies':0,'household_activation':False,'real_family_data':False};gateway=None;worker=None;bank=None
    initial=ledger.used_micro_usd();ceiling=min(APPROVED_BUDGET_MICRO_USD,initial+1_000_000)
    started=time.monotonic();maximum=plan['limits']['maximum_wall_seconds']
    result['preflight']=await wait_native_readiness()
    audit(source.parent)
    original=readonly_view(source/'learning.sqlite3')
    bundle=create_bundle(source,folder,source_realm='fixture');verify_bundle(bundle)
    restored=restore_bundle(bundle,folder);review=rebuild_plan(restored,current_queue=source/'learning.sqlite3')
    if review['status']!='needs_native_rebuild' or len(review['completed_source_candidates'])!=7 or len(review['excluded_revoked'])!=1:
        raise ValueError('Only exact seven completed sources and one revoked source may enter this rebuild')
    result.update(bundle=str(bundle),offline_source_copy=str(restored),review=review,source_before=original)
    stage=folder/'offline-native-rebuild';stage.mkdir(mode=0o700)
    # Preserve quarantine before copying any authority. No live-restore override.
    marker={'automatic_replay_allowed':False,'can_activate_live':False,'reason':'Offline fictional native rebuild qualification only.'}
    (stage/'RESTORE_OFFLINE_ONLY.json').write_text(json.dumps(marker)+'\n')
    src=sqlite3.connect((restored/'queue.sqlite3').as_uri()+'?mode=ro',uri=True);dest=sqlite3.connect(stage/'learning.sqlite3')
    try:src.backup(dest)
    finally:src.close();dest.close()
    directory=native_directory(stage,source_realm='fixture');logs=folder/'worker-logs';logs.mkdir(mode=0o700)
    result['new_generation']=directory.name!=native_directory(source,source_realm='fixture').name
    result['staging_root']=str(stage);result['native_directory']=str(directory)
    try:
        gateway=LearningGateway(folder,project_ceiling_micro_usd=ceiling,maximum_calls=32)
        result['gateway_receipt']=await asyncio.to_thread(gateway.start)
        worker=Process('hindsight',directory,logs,'learning_worker.py',source_realm='fixture')
        await asyncio.to_thread(send,worker,{'op':'initialize'})
        if await asyncio.to_thread(send,worker,{'op':'inventory','people':people}):raise ValueError('New index is not empty')
        result['rebuilt_sources']=[]
        for episode in original['sources']:
            if time.monotonic()-started>maximum:raise TimeoutError('Rebuild deadline; no automatic retry')
            await asyncio.to_thread(send,worker,{'op':'ingest','episode':episode,'people':people})
            result['rebuilt_sources'].append(episode['id'])
            (folder/'progress.json').write_text(json.dumps(result,indent=2)+'\n')
            print(json.dumps({'rebuilt':len(result['rebuilt_sources']),'of':7}),flush=True)
        inventory=await asyncio.to_thread(send,worker,{'op':'inventory','people':people})
        result['projection']=projection_report(original,inventory)
        from experiments.memory.native_recovery_trial import connect
        c=connect()
        try:
            with c.cursor() as cur:
                prefix='pilot'+directory.name.replace('-','')+'-%'
                cur.execute('SELECT count(*) FROM documents WHERE bank_id LIKE %s',(prefix,));result['native_documents']=cur.fetchone()[0]
                cur.execute('SELECT count(*),count(*) FILTER (WHERE embedding IS NOT NULL AND vector_dims(embedding)=384) FROM memory_units WHERE bank_id LIKE %s',(prefix,))
                n,valid=cur.fetchone();result['native_vectors_rebuilt']=n>0 and n==valid
        finally:c.close()
        result['pre_close']=await wait_native_readiness(expected_paid=True,maximum_seconds=30)
        await asyncio.to_thread(worker.stop);worker=None
        await asyncio.to_thread(gateway.close)
        result['paid_disabled_before_reopen']=(await wait_native_readiness())['paid_enabled'] is False
        # Reopen the actual native worker without enabling another paid cycle.
        bank=HouseholdMemory(people,storage_root=stage,source_realm='fixture')
        bank.directory=directory;bank.queue=read_queue(stage/'learning.sqlite3')
        bank.worker=Process('hindsight',directory,logs,'learning_worker.py',source_realm='fixture')
        await asyncio.to_thread(bank._send,{'op':'initialize'})
        fresh=await asyncio.to_thread(bank._send,{'op':'inventory','people':people})
        result['reopen_projection']=projection_report(bank.queue.evidence_snapshot(),fresh)
        import tiktoken
        os.environ['TIKTOKEN_CACHE_DIR']=str(SSD/'models/tiktoken');bank.encoding=tiktoken.get_encoding('o200k_base')
        stat=Path(bank.queue.path).stat();bank.storage_identity=(stat.st_dev,stat.st_ino);bank.ready=True
        base={'actual_speaker_id':'mira','people':people,'audience_ids':list(people),'conversation_at':'2026-11-09T12:00:00Z'}
        breakfast=await bank.recall({**base,'question':'What breakfast does Leon want now?'})
        privacy=await bank.recall({**base,'question':'What is Nora making for her surprise project?'})
        result['correction_source_recalled']=any('Oatmeal with bananas' in f['text'] for f in breakfast['evidence']['facts'])
        result['private_and_revoked_excluded']=all('miniature railway' not in json.dumps(x['evidence']) and 'beetle stickers' not in json.dumps(x['evidence']) for x in (breakfast,privacy))
        result['retrieval_contexts']={'breakfast':breakfast['evidence'],'privacy':privacy['evidence']}
        result['source_copy_unchanged']=bank.queue.evidence_snapshot()==original
        await bank.close();bank=None
        try:unsafe=LearningQueue(stage/'learning.sqlite3');unsafe.close();result['offline_adoption_blocked']=False
        except ValueError:result['offline_adoption_blocked']=True
    finally:
        if bank:await bank.close()
        if worker:await asyncio.to_thread(worker.stop)
        if gateway:await asyncio.to_thread(gateway.close)
        calls=folder/'gateway/calls.json';result['gateway_calls']=json.loads(calls.read_text()) if calls.exists() else []
        events=result['gateway_calls']
        result['usage_verified']=bool(events) and all(e.get('model')==MODEL and e.get('rates_micro_usd')==list(MODEL_RATES[MODEL])
            and e.get('http_status')==200 and isinstance(e.get('actual_micro_usd'),int)
            and ledger.db.execute('SELECT actual FROM spending WHERE id=?',(e['id'],)).fetchone()==(e['actual_micro_usd'],)
            and digest(folder/'gateway'/f'{i:04d}-request.json')==e['request_sha256'] for i,e in enumerate(events,1))
        result['additional_api_usd']=(ledger.used_micro_usd()-initial)/1e6
        result['source_original_unchanged']=readonly_view(source/'learning.sqlite3')==original
        result['parent_audit_valid']=audit(source.parent)['valid']
        result['final_readiness']=await wait_native_readiness()
        (folder/'collection.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def run():
    os.umask(0o077);require_ssd();protocol=ROOT/'experiments/reliability/memory-rebuild-protocol-v1.json';plan=read_protocol(protocol)
    if list((SSD/'runs/scored'/plan['experiment_id']).glob('*/run.json')):raise ValueError('No automatic repeat')
    # Never alter the paid ledger during the independent zero-cost idle soak.
    prior=[audit(p.parent) for p in discover_runs()]
    current=status()
    if not current['idle'] or not current['family_off'] or HouseholdMemory.qualified:
        raise ValueError('Leave active session unchanged; calibration and household activation stay parked')
    soak=json.loads((ROOT/'docs/evaluations/paprika_mac_reliability_02.json').read_text())
    if soak['audit']['experiment_id']!='MAC-RELIABILITY-02' or soak['decision']['outcome']!='pass':raise ValueError('Complete the frozen idle screen first')
    import importlib.metadata
    env=json.loads((ROOT/'experiments/memory/learning-environment-v1.json').read_text())
    if any(importlib.metadata.version(k)!=v for k,v in env['versions'].items()):raise ValueError('Pinned environment changed')
    folder,plan=begin(protocol,run_root=SSD/'runs/scored');ledger=Store(ROOT/'.tavi/simulation/simulation.sqlite3',must_exist=True)
    initial=ledger.used_micro_usd();errors=[];data={}
    try:data=asyncio.run(collect(folder,plan,ledger))
    except Exception as e:
        errors.append(type(e).__name__+': '+str(e))
        if (folder/'collection.json').exists():data=json.loads((folder/'collection.json').read_text())
    metrics={k:data.get(k) for k in ('new_generation','paid_disabled_before_reopen','correction_source_recalled','private_and_revoked_excluded','source_copy_unchanged','offline_adoption_blocked','source_original_unchanged','native_vectors_rebuilt','usage_verified','parent_audit_valid')}
    if HouseholdMemory.qualified:errors.append('Unexpected household activation')
    metrics.update(native_documents=data.get('native_documents'),rebuilt_sources=len(data.get('rebuilt_sources',[])),projection_consistent=data.get('projection',{}).get('can_resume'),
                   reopen_consistent=data.get('reopen_projection',{}).get('can_resume'),final_paid_disabled=data.get('final_readiness',{}).get('paid_enabled') is False,
                   model_replies=data.get('model_replies'),additional_api_usd=(ledger.used_micro_usd()-initial)/1e6,collection_errors=len(errors))
    ledger.close();(folder/'observations.json').write_text(json.dumps({'metrics':metrics,'data':data,'errors':errors},indent=2)+'\n')
    artifacts=[p for p in folder.rglob('*') if p.is_file() and p.name not in ('run.json','protocol.json') and not set(p.relative_to(folder).parts)&{'source','context'}]
    record=finish(folder,metrics,artifacts=artifacts,completed=not errors,error='; '.join(errors) or None)
    report={'date':'2026-11-10 America/Toronto','run':str(folder),'metrics':metrics,'decision':record['decision'],'audit':audit(folder),'data':data,'errors':errors,
            'critical_review':['Actual new-generation native Hindsight rebuild of seven existing authored development sources, not new independent quality evidence or an engine sweep.',
                               'One local paid extraction gateway with32-call/1USDstage ceiling under31USDproject cap; all background calls included. No response generation or real family input.',
                               'New index remains quarantined offline; original source bank, deletion, attribution and correction preserved. Original6/8reply quality and prior errors unchanged.',
                               'Source-based rebuild regenerates derivatives, not byte-identical extracted facts; retrieval checks are small reused development controls, not fullE5.',
                               'No physical power/drive loss, automatic adoption or qualification of identity/household memory.']}
    (ROOT/'docs/evaluations/paprika_memory_rebuild_01.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'run':str(folder),'decision':record['decision']['outcome'],'metrics':metrics,'errors':errors}),flush=True)


if __name__=='__main__':run()
