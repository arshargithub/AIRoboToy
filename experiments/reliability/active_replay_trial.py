"""Frozen active controller replay + actual local K/turbo synthetic smoke."""
import asyncio
import json
import os
from pathlib import Path
import re
from experiments.memory.runtime import ROOT,SSD,require_ssd
from experiments.memory.household_integration_trial import command
from experiments.reliability.active_replay import ActiveReplay
from experiments.reliability.local_synthetic_smoke import run as local_smoke
from experiments.reliability.mac_reliability_trial import status
from tavi.experiment_workflow import begin,finish,audit,discover_runs,read_protocol
from tavi.storage import Store


async def exercise():
    import threading
    baseline=set(asyncio.all_tasks());r=ActiveReplay()
    try:data=await r.run(batches=30)
    finally:await r.close()
    await asyncio.sleep(.01)
    data['no_voice_threads_after_close']=not any(t.name=='paprika-voice-score' for t in threading.enumerate())
    data['no_extra_async_tasks_after_close']=not (set(asyncio.all_tasks())-baseline)
    return data


def run():
    os.umask(0o077);require_ssd();path=ROOT/'experiments/reliability/active-replay-protocol-v1.json';plan=read_protocol(path)
    if list((SSD/'runs/scored'/plan['experiment_id']).glob('*/run.json')):raise ValueError('No automatic repeat')
    checks=[audit(p.parent) for p in discover_runs()];live=status()
    if not live['idle'] or not live['family_off']:raise ValueError('Leave active user session unchanged')
    folder,plan=begin(path,run_root=SSD/'runs/scored');print(json.dumps({'run':str(folder),'prior_valid':len(checks)}),flush=True)
    ledger=Store(ROOT/'.tavi/simulation/simulation.sqlite3',must_exist=True);initial=ledger.used_micro_usd();data={};errors=[]
    try:
        data['replay']=asyncio.run(exercise());print(json.dumps({'phase':'controller','turns':data['replay']['completed_turns'],'probes':data['replay']['probes_passed']}),flush=True)
        data['local_smoke']=asyncio.run(local_smoke());print(json.dumps({'phase':'local-K-turbo','intents':[c['intent_present'] for c in data['local_smoke']['clips']]}),flush=True)
        out=command(folder,'python-tests',[str(ROOT/'.venv-tavi/bin/python'),'-m','unittest','discover','-s','tests'])
        data['python_tests']=int(re.search(r'Ran (\d+) tests',out).group(1))
        out=command(folder,'ui-tests',['node','--test','--test-reporter=tap',*map(str,sorted((ROOT/'tests').glob('*.cjs')))])
        data['ui_tests']=int(re.search(r'# pass (\d+)',out).group(1))
        data['runtime_after']=status()
    except Exception as e:errors.append(type(e).__name__+': '+str(e))
    replay=data.get('replay',{});local=data.get('local_smoke',{})
    metrics={k:replay.get(k) for k in ('completed_turns','probes_passed','maximum_history','maximum_chunks','all_references_closed','no_memory_access','fixture_uncertain_reservations_preserved','no_voice_threads_after_close','no_extra_async_tasks_after_close')}
    metrics.update(local_intents_passed=sum(c['intent_present'] for c in local.get('clips',[])),local_workers_closed=local.get('workers_closed'),local_holds_released=local.get('holds_released'),
        python_tests_passed=data.get('python_tests'),ui_tests_passed=data.get('ui_tests'),runtime_idle=data.get('runtime_after',{}).get('idle'),
        family_off=data.get('runtime_after',{}).get('family_off'),prompt_unchanged=data.get('runtime_after',{}).get('prompt')==live['prompt'],
        additional_api_usd=(ledger.used_micro_usd()-initial)/1e6,collection_errors=len(errors))
    ledger.close();(folder/'observations.json').write_text(json.dumps({'data':data,'metrics':metrics,'errors':errors},indent=2)+'\n')
    artifacts=[p for p in folder.rglob('*') if p.is_file() and p.name not in ('run.json','protocol.json') and not set(p.relative_to(folder).parts)&{'source','context'}]
    record=finish(folder,metrics,artifacts=artifacts,completed=not errors,error='; '.join(errors) or None)
    report={'date':'2026-11-10 America/Toronto','run':str(folder),'metrics':metrics,'decision':record['decision'],'audit':audit(folder),'data':data,'errors':errors,
        'critical_review':['Three hundred active turns exercise current unqualified/anonymous HouseholdRuntime→CompanionText→NativeTextReference→sentence controller, with controlled native transport and valid tone WAVs. Recognition events and playback acknowledgements are simulated.',
                           'Fourteen probes include standby/control/offline, incomplete/failed output, speech failure, cancelled generation, mute/scope changes, interruption, stale reconnect data, frame expiry, goodbye and12-turn bound. No personal-bank or encoder call permitted.',
                           'Separate actual unchanged K/turbo in-memory synthetic clips exercise real local model processes and existing inference scheduler/3s final bound. Not real human word accuracy, wake/acoustics, physical playback or voice recognition.',
                           'The controller workload is fast replay, not an elapsed-time soak. Intentional harness references are retained for auditing; no heap/RSS leak claim follows. Production queues/history/task owners and cleanup are checked.',
                           'Only a disposable in-memory fixture ledger accounts fake model tokens. Global paid ledger unchanged; calibration and household activation remain parked. No production code or personality changes.']}
    (ROOT/'docs/evaluations/paprika_active_replay_01.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'decision':record['decision']['outcome'],'metrics':metrics,'errors':errors,'run':str(folder)}),flush=True)


if __name__=='__main__':run()
