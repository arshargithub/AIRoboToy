"""Prospective fixture repair: bind every pending probe to its own new request."""
import asyncio
import json
import os
import re
from experiments.memory.runtime import ROOT, SSD, require_ssd
from experiments.memory.household_integration_trial import command
from experiments.reliability.active_replay_trial import exercise
from experiments.reliability.mac_reliability_trial import status
from tavi.experiment_workflow import begin, finish, audit, discover_runs, read_protocol
from tavi.storage import Store


def run():
    os.umask(0o077);require_ssd()
    path=ROOT/'experiments/reliability/active-replay-protocol-v2.json';plan=read_protocol(path)
    if list((SSD/'runs/scored'/plan['experiment_id']).glob('*/run.json')):raise ValueError('No automatic scored repeat')
    checked=[audit(p.parent) for p in discover_runs()];live=status()
    if not live['idle'] or not live['family_off']:raise ValueError('Leave active session unchanged')
    folder,plan=begin(path,run_root=SSD/'runs/scored');print(json.dumps({'run':str(folder),'prior_valid':len(checked)}),flush=True)
    ledger=Store(ROOT/'.tavi/simulation/simulation.sqlite3',must_exist=True);initial=ledger.used_micro_usd();data={};errors=[]
    try:
        data['replay']=asyncio.run(exercise())
        out=command(folder,'python-tests',[str(ROOT/'.venv-tavi/bin/python'),'-m','unittest','discover','-s','tests'])
        data['python_tests']=int(re.search(r'Ran (\d+) tests',out).group(1))
        data['runtime_after']=status()
    except Exception as error:errors.append(type(error).__name__+': '+str(error))
    r=data.get('replay',{});s=data.get('runtime_after',{})
    metrics={k:r.get(k) for k in ('completed_turns','probes_passed','maximum_history','maximum_chunks','all_references_closed','no_memory_access','fixture_uncertain_reservations_preserved','no_voice_threads_after_close','no_extra_async_tasks_after_close')}
    trace={row['probe']:row for row in r.get('trace',[])}
    metrics.update(pending_probes_dispatched=sum(trace.get(name,{}).get('requests')==1 for name in ('cancel-generation','mute-pending','scope-change')),
        python_tests_passed=data.get('python_tests'),runtime_idle=s.get('idle'),family_off=s.get('family_off'),prompt_unchanged=s.get('prompt')==live['prompt'],
        additional_api_usd=(ledger.used_micro_usd()-initial)/1e6,collection_errors=len(errors))
    ledger.close();(folder/'observations.json').write_text(json.dumps({'data':data,'metrics':metrics,'errors':errors},indent=2)+'\n')
    artifacts=[p for p in folder.iterdir() if p.is_file() and p.name not in ('run.json','protocol.json')]
    result=finish(folder,metrics,artifacts=artifacts,completed=not errors,error='; '.join(errors) or None)
    report={'date':'2026-11-10 America/Toronto','run':str(folder),'metrics':metrics,'decision':result['decision'],'audit':audit(folder),'data':data,'errors':errors,
        'critical_review':['Original ACTIVE-REPLAY-01 automated screen said pass, but post-run review found mute/scope probes dispatched zero requests: an older pending event satisfied their wait. The original record is immutable; only12of14original probe results support the intended coverage.',
            'New assertion failed before repair. Corrected harness waits for exactly one new reference, its own pending event and closed cleanup. All three pending probes must dispatch exactly one new request. Production code/limits unchanged.',
            'Fresh300controller turns and14probes; controlled transport/recognition/playback and valid tone WAVs only. No actual ASR/K/model calls in this follow-up, wall-time soak or heap-leak claim.',
            'Actual local K/turbo two-clip smoke remains separate valid evidence from01; not rerun or counted as fresh here. Its first transcript omits Paprika; both intents passed but no wake-name claim.',
            'Original713Python/57UI suites remain historical evidence; full Python rerun now includes the corrected pending assertion. Household memory/recognition remain off, calibration parked.']}
    (ROOT/'docs/evaluations/paprika_active_replay_02.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'decision':result['decision']['outcome'],'metrics':metrics,'errors':errors}),flush=True)


if __name__=='__main__':run()
