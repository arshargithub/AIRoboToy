"""Complete only the interrupted restart checkpoint; no learned/reply retries."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import time

from experiments.memory.household_model_trial import wait_native_readiness
from experiments.memory.learning_gateway import LearningGateway
from experiments.memory.learning_queue import LearningQueue
from experiments.memory.runtime import ROOT,SSD,require_ssd
from tavi.experiment_workflow import begin,finish,audit,discover_runs,read_protocol,digest
from tavi.household_memory import HouseholdMemory
from tavi.memory_projection import projection_report
from tavi.storage import Store


def readonly_view(path):
    q=LearningQueue.__new__(LearningQueue);q.db=sqlite3.connect(Path(path).as_uri()+'?mode=ro',uri=True);q.db.row_factory=sqlite3.Row
    try:return q.evidence_snapshot()
    finally:q.close()


def expected_view(parent,revoke_alias):
    result=deepcopy(parent['queue_before']);sid=parent['sources'][revoke_alias]
    if result['epoch']!=0 or result['revoked_source_ids'] or len(result['sources'])!=8:
        raise ValueError('Unexpected original source state')
    result['epoch']=1;result['sources']=[s for s in result['sources'] if s['id']!=sid];result['revoked_source_ids']=[sid]
    record=next(r for r in result['records'] if r['id']==sid)
    if record['state']!='complete' or record['revision']!=1:raise ValueError('Original revocation source changed')
    record.update(state='revoked',revision=2)
    return result


async def collect(folder,plan,parent):
    source=Path(plan['configuration']['parent_folder']);fixture=source/'fixture-household'
    data=json.loads((ROOT/'experiments/memory/household-model-input-v1.json').read_text())
    before=readonly_view(fixture/'learning.sqlite3');expected=expected_view(parent,data['revoke_alias'])
    if before!=expected:raise ValueError('Source state differs from original sources plus recorded revocation')
    if json.loads((fixture/'native-generation.json').read_text())!=parent['namespace_manifest']:raise ValueError('Original bank identity changed')
    gateway=None
    def factory(control):
        nonlocal gateway
        if gateway is not None:raise ValueError('Only one remaining gateway cycle')
        gateway=LearningGateway(control,project_ceiling_micro_usd=parent['combined_ceiling_micro_usd'],maximum_calls=0)
        return gateway
    bank=HouseholdMemory(data['people'],storage_root=fixture,gateway_factory=factory,source_realm='fixture')
    result={'before':before,'learning_replayed':False,'reply_calls':0}
    try:
        result['preflight']=await wait_native_readiness()
        await bank.prepare()
        async with asyncio.timeout(30):
            while bank.supervisor.snapshot()['status']!='idle':
                state=bank.supervisor.snapshot()['status']
                if state in ('needs_reconciliation','owner_busy','job_bound'):raise ValueError('Restart worker: '+state)
                await asyncio.sleep(.05)
        inventory=await asyncio.to_thread(bank._send,{'op':'inventory','people':data['people']})
        after=bank.queue.evidence_snapshot();result.update(after=after,
            same_generation_after_restart=str(bank.directory)==parent['native_directory'],
            source_state_preserved=before==after,projection=projection_report(after,inventory),
            supervisor=bank.supervisor.snapshot(),gateway_receipt=gateway.health())
    finally:
        try:await bank.close()
        finally:
            if gateway:await asyncio.to_thread(gateway.close)
    result['final_readiness']=await wait_native_readiness()
    calls=gateway.folder/'gateway/calls.json' if gateway else None
    result['gateway_calls']=json.loads(calls.read_text()) if calls and calls.exists() else []
    return result


def run():
    require_ssd();os.umask(0o077);protocol=ROOT/'experiments/memory/household-restart-protocol-v1.json';plan=read_protocol(protocol)
    if list((SSD/'runs/scored'/plan['experiment_id']).glob('*/run.json')):raise ValueError('No automatic restart-check repeat')
    checks=[audit(p.parent) for p in discover_runs()];source=Path(plan['configuration']['parent_folder']);audit(source)
    record=json.loads((source/'run.json').read_text());parent=json.loads((source/'observations.json').read_text())
    if record['decision']['outcome']!='error' or len(parent['cases'])!=4 or not all(c['completed'] for c in parent['cases']):
        raise ValueError('Original interrupted checkpoint does not match')
    if parent['completed_ingestions']!=8 or parent['gateway_cycles']!=1 or not parent['revoked_context_excluded'] or 'native_delete' not in parent:
        raise ValueError('Original completed work missing')
    original_sha=digest(source/'observations.json');ledger=Store(ROOT/'.tavi/simulation/simulation.sqlite3',must_exist=True);initial=ledger.used_micro_usd()
    if initial!=27529669:raise ValueError('Ledger changed; do not misbind continuation')
    folder,plan=begin(protocol,run_root=SSD/'runs/scored');print(json.dumps({'run':str(folder),'prior_valid':len(checks),'audit':audit(folder)}),flush=True)
    errors=[];data={}
    try:data=asyncio.run(collect(folder,plan,parent))
    except Exception as e:errors.append(type(e).__name__+': '+str(e))
    metrics={'same_generation_after_restart':data.get('same_generation_after_restart'),
        'source_state_preserved':data.get('source_state_preserved'),'projection_consistent':data.get('projection',{}).get('can_resume'),
        'no_learning_replay':data.get('supervisor',{}).get('completed')==0,'gateway_limit_zero':data.get('gateway_receipt',{}).get('maximum_calls')==0,
        'no_new_model_requests':data.get('gateway_calls')==[],'parent_unchanged':digest(source/'observations.json')==original_sha,
        'final_paid_disabled':data.get('final_readiness',{}).get('paid_enabled') is False,
        'collection_errors':len(errors),'additional_api_usd':(ledger.used_micro_usd()-initial)/1e6}
    ledger.close();(folder/'observations.json').write_text(json.dumps({'metrics':metrics,'data':data,'errors':errors},indent=2)+'\n')
    r=finish(folder,metrics,artifacts=[folder/'observations.json'],completed=not errors,error=';'.join(errors) or None)
    report={'date':'2026-11-09 America/Toronto','run':str(folder),'parent':str(source),'metrics':metrics,'decision':r['decision'],'audit':audit(folder),
        'data':data,'errors':errors,'critical_review':['Only missing restart verified; original8sources/4replies/usage/labels and sealed error remain unchanged.',
        'Actual adapter, worker, bank identity, native source-document checks and source/tombstone persistence exercised; second gateway quota0prevents a new inference request.',
        'Maintenance readiness now polls only local busy state under a bound; connection/config errors still fail immediately. No ambiguous learning or paid request retried.',
        'This pass does not override original6/8usefulness or qualify calibration, live household memory or fullE5/E6.']}
    (ROOT/'docs/evaluations/paprika_household_restart_01.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'run':str(folder),'decision':r['decision']['outcome'],'metrics':metrics,'errors':errors}),flush=True)


if __name__=='__main__':run()
