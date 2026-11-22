"""Actual owned worker crash + final no-inference application qualification."""
import asyncio
import json
import os
from pathlib import Path
import re

from experiments.memory.access_evidence import with_access_decision
from experiments.memory.conversation_adapter import MemoryTextProvider
from experiments.memory.household_integration_trial import command,STOP_IDLE,VERIFY
from experiments.memory.household_model_trial import wait_native_readiness
from experiments.memory.household_restart_trial import readonly_view
from experiments.memory.learning_queue import LearningQueue
from experiments.memory.pilot import Process
from experiments.memory.runtime import ROOT,SSD,require_ssd
from experiments.memory.worker_transport import MemoryWorkerUnavailable,MemoryWorkerTimeout
from tavi.experiment_workflow import begin,finish,audit,discover_runs,read_protocol
from tavi.household_memory import HouseholdMemory
from tavi.memory_generation import native_directory
from tavi.storage import Store


async def native_crash(folder,source):
    people=json.loads((ROOT/'experiments/memory/household-model-input-v1.json').read_text())['people']
    root=source/'fixture-household';before=readonly_view(root/'learning.sqlite3')
    bank=HouseholdMemory(people,storage_root=root,source_realm='fixture')
    bank.queue=LearningQueue(root/'learning.sqlite3');bank.directory=native_directory(root,source_realm='fixture')
    logs=folder/'native-logs';logs.mkdir(mode=0o700)
    bank.worker=Process('hindsight',bank.directory,logs,'learning_worker.py',source_realm='fixture')
    store=Store();sent=[];provider=None;result={}
    class NoInference:
        async def connect(self):pass
        async def close(self):pass
        async def stream_text(self,*args):
            sent.append(True);raise AssertionError('Retired memory must prevent inference')
            yield ''
    try:
        await asyncio.to_thread(bank._send,{'op':'initialize'})
        await asyncio.to_thread(bank._send,{'op':'inventory','people':people})
        bank.ready=True;issued=bank.generation()
        # Kill only this explicitly owned disposable query child, never the
        # shared native server or another user's process.
        bank.worker.process.kill();bank.worker.process.wait(timeout=3)
        scope=lambda:{'session_id':'read-only-crash','memory_epoch':bank.generation(),'task':{
            'actual_speaker_id':'mira','people':people,'audience_ids':list(people),
            'conversation_at':'2026-11-09T12:00:00Z','catalogue':[]}}
        provider=MemoryTextProvider(store,scope=scope,recall=bank.recall,reference_factory=lambda s:NoInference(),evidence_qualifier=with_access_decision)
        try:
            async for _ in provider.stream_reply([{'role':'user','content':'A read-only recovery probe.'}]):pass
        except (MemoryWorkerUnavailable,MemoryWorkerTimeout):result['typed_worker_failure']=True
        else:result['typed_worker_failure']=False
        result.update(memory_not_ready=not bank.ready,generation_retired=bank.generation()!=issued,
            no_reply_request=not sent,status=bank.status())
    finally:
        if provider:await provider.close()
        await bank.close();store.close()
    result['source_state_unchanged']=readonly_view(root/'learning.sqlite3')==before
    result['native_ready']=await wait_native_readiness()
    return result


def run():
    os.umask(0o077);require_ssd();path=ROOT/'experiments/memory/household-fault-protocol-v1.json';plan=read_protocol(path)
    if list((SSD/'runs/scored'/plan['experiment_id']).glob('*/run.json')):raise ValueError('No automatic scored repeat')
    checks=[audit(p.parent) for p in discover_runs()]
    source=Path(plan['configuration']['model_run']);audit(source)
    restart=json.loads((ROOT/'docs/evaluations/paprika_household_restart_01.json').read_text());audit(restart['run'])
    if restart['decision']['outcome']!='pass':raise ValueError('Restart predecessor must pass')
    folder,plan=begin(path,run_root=SSD/'runs/scored');print(json.dumps({'run':str(folder),'prior_valid':len(checks),'audit':audit(folder)}),flush=True)
    store=Store(ROOT/'.tavi/simulation/simulation.sqlite3',must_exist=True);initial=store.used_micro_usd();data={};errors=[]
    try:
        data['crash']=asyncio.run(native_crash(folder,source))
        out=command(folder,'python-tests',[str(ROOT/'.venv-tavi/bin/python'),'-m','unittest','discover','-s','tests'])
        data['python_tests']=int(re.search(r'Ran (\d+) tests',out).group(1))
        for name,files in [('ui-tests',sorted((ROOT/'tests').glob('*.cjs'))),('desktop-tests',sorted((ROOT/'desktop/test').glob('*.test.cjs')))]:
            out=command(folder,name,['node','--test','--test-reporter=tap',*map(str,files)])
            data[name]=int(re.search(r'# pass (\d+)',out).group(1))
        command(folder,'stop-idle',['node','-e',STOP_IDLE],timeout=40)
        env={**os.environ,'PAPRIKA_RECOVERY_REPORT':str(folder/'renderer-recovery.json'),'PAPRIKA_EXPECTED_BUDGET_USD':'31'}
        command(folder,'renderer',[str(ROOT/'desktop/node_modules/.bin/electron'),str(ROOT/'desktop/test/memory-recovery-smoke.cjs')],env=env,timeout=40)
        data['renderer']=json.loads((folder/'renderer-recovery.json').read_text())
        command(folder,'reopen',['open',str(ROOT/'.tavi/mac/build/Paprika-darwin-arm64/Paprika.app')],timeout=10)
        out=command(folder,'fresh-runtime',['node','-e',VERIFY],timeout=30);data['runtime']=json.loads(out.strip())
    except Exception as e:errors.append(type(e).__name__+': '+str(e))
    metrics={k:data.get('crash',{}).get(k) for k in ['typed_worker_failure','memory_not_ready','generation_retired','no_reply_request','source_state_unchanged']}
    metrics.update(python_tests_passed=data.get('python_tests'),ui_tests_passed=data.get('ui-tests'),desktop_tests_passed=data.get('desktop-tests'),
        renderer_passed=data.get('renderer',{}).get('passed'),runtime_idle=data.get('runtime',{}).get('idle'),budget_refreshed=data.get('runtime',{}).get('budget_usd')==31,
        prompt_unchanged=data.get('runtime',{}).get('prompt_sha256')==plan['configuration']['prompt_sha256'],
        paid_disabled=data.get('crash',{}).get('native_ready',{}).get('paid_enabled') is False,
        collection_errors=len(errors),additional_api_usd=(store.used_micro_usd()-initial)/1e6)
    store.close();(folder/'observations.json').write_text(json.dumps({'metrics':metrics,'data':data,'errors':errors},indent=2)+'\n')
    artifacts=[p for p in folder.rglob('*') if p.is_file() and p.name not in ('run.json','protocol.json') and not set(p.relative_to(folder).parts)&{'source','context'}]
    r=finish(folder,metrics,artifacts=artifacts,completed=not errors,error=';'.join(errors) or None)
    report={'date':'2026-11-09 America/Toronto','run':str(folder),'metrics':metrics,'decision':r['decision'],'audit':audit(folder),'data':data,'errors':errors,
        'critical_review':['Killed only an owned disposable query worker against the authored fixture; no native server, bank, source or voice-profile destruction.',
        'No gateway start or inference request. Bank readiness/context are retired and no reply generation occurs; corrected controller preserves the actionable memory error without exposing stale text.',
        'Explicit source realms keep fixtures from becoming household authority; legacy unlabelled generations remain fixture-only and are not rewritten.',
        'Full current local tests and actual idle Mac renderer verify recovery and31USDcap. No microphone, calibration, prompt change or household activation.',
        'Original model run stays error with4/4functional and6/8usefulness; recovered restart passed separately. This screen cannot turn that into a model-quality or productpass.']}
    (ROOT/'docs/evaluations/paprika_household_fault_01.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'run':str(folder),'decision':r['decision']['outcome'],'metrics':metrics,'errors':errors}),flush=True)


if __name__=='__main__':run()
