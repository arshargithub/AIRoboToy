"""Local controller/renderer qualification after native recovery fixtures.

No positive microphone choice, real calibration, live memory activation or
inference. An active user capture prevents the desktop restart check.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import time

from experiments.memory.runtime import ROOT, SSD, require_ssd
from tavi.experiment_workflow import begin,finish,audit,discover_runs,read_protocol,digest
from tavi.storage import Store


def command(folder,name,args,*,env=None,timeout=120):
    result=subprocess.run(args,cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=timeout)
    (folder/(name+'.log')).write_bytes(result.stdout)
    if result.returncode:raise RuntimeError(name+' failed; see preserved log')
    return result.stdout.decode(errors='replace')


STOP_IDLE=r"""
const {CoreOwner}=require('./desktop/owner.cjs');const {spawnSync}=require('node:child_process');const sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{const o=new CoreOwner(process.cwd());const r=o.read();if(r){await o.verify(r);const d=await o.request('/api/conversation/diagnostics');if(d.lease_active!==false)throw Error('Active user capture: restart deferred');}
const q=spawnSync('/usr/bin/osascript',['-e','if application id "local.paprika.prototype" is running then tell application id "local.paprika.prototype" to quit'],{encoding:'utf8',timeout:15000});if(q.status!==0)throw Error('App did not quit cleanly');
for(let n=0;n<100&&o.read();n++)await sleep(100);if(o.read())await o.stop();console.log('Owned idle app stopped gracefully');})().catch(e=>{console.error(e.message);process.exitCode=1;});
"""
VERIFY=r"""
const {CoreOwner}=require('./desktop/owner.cjs');const sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{const o=new CoreOwner(process.cwd());for(let n=0;n<100;n++){if(o.read()){try{const s=await o.verify(o.read());const d=await o.request('/api/conversation/diagnostics');if(d.lease_active!==false||s.family.family_voice_enabled||s.family.family_memory_requested||s.family.memory.ready)throw Error('Unexpected active family/capture state');console.log(JSON.stringify({idle:true,calibration_started:false,memory_enabled:false,prompt_sha256:s.reply_prompt_sha256,recovery_status:s.family.memory.recovery_status,budget_usd:s.budget_usd,spent_reserved_usd:s.spent_or_reserved_usd}));return;}catch(e){if(n===99)throw e;}}await sleep(100);}throw Error('Fresh app timeout');})().catch(e=>{console.error(e.message);process.exitCode=1;});
"""


def run(protocol=None):
    require_ssd();os.umask(0o077)
    protocol=Path(protocol) if protocol else ROOT/'experiments/memory/household-integration-protocol-v1.json';plan=read_protocol(protocol)
    if list((SSD/'runs/scored'/plan['experiment_id']).glob('*/run.json')):raise ValueError('No automatic scored retry')
    checks=[audit(p.parent) for p in discover_runs()]
    previous=json.loads((ROOT/'docs/evaluations/paprika_household_recovery_01.json').read_text())
    if audit(previous['run'])['decision']!='pass':raise ValueError('Native recovery predecessor must pass')
    native_record=json.loads((Path(previous['run'])/'run.json').read_text())
    for name in ('tavi/memory_projection.py','experiments/memory/worker.py','experiments/memory/learning_worker.py',
                 'experiments/memory/learning_queue.py','experiments/memory/source_context.py','experiments/memory/queue_snapshot.py'):
        if digest(ROOT/name)!=native_record['source_sha256'][name]:raise ValueError('Native helper changed; qualify it separately')
    folder,plan=begin(protocol,run_root=SSD/'runs/scored');print(json.dumps({'run':str(folder),'prior_valid':len(checks),'audit':audit(folder)}),flush=True)
    ledger=Store(ROOT/'.tavi/simulation/simulation.sqlite3',must_exist=True);initial=ledger.used_micro_usd();errors=[];data={};start=time.monotonic()
    try:
        out=command(folder,'python-tests',[str(ROOT/'.venv-tavi/bin/python'),'-m','unittest','discover','-s','tests'])
        data['python_tests']=int(re.search(r'Ran (\d+) tests',out).group(1))
        for name,files in [('ui-tests',sorted((ROOT/'tests').glob('*.cjs'))),('desktop-tests',sorted((ROOT/'desktop/test').glob('*.test.cjs')))]:
            out=command(folder,name,['node','--test','--test-reporter=tap',*map(str,files)])
            data[name]=int(re.search(r'# pass (\d+)',out).group(1))
        command(folder,'stop-idle',['node','-e',STOP_IDLE],timeout=40)
        env={**os.environ,'PAPRIKA_RECOVERY_REPORT':str(folder/'renderer-recovery.json')}
        command(folder,'renderer',[str(ROOT/'desktop/node_modules/.bin/electron'),str(ROOT/'desktop/test/memory-recovery-smoke.cjs')],env=env,timeout=40)
        data['renderer']=json.loads((folder/'renderer-recovery.json').read_text())
        command(folder,'reopen',['open',str(ROOT/'.tavi/mac/build/Paprika-darwin-arm64/Paprika.app')],timeout=10)
        out=command(folder,'fresh-runtime',['node','-e',VERIFY],timeout=30);data['runtime']=json.loads(out.strip())
    except Exception as error:errors.append(type(error).__name__+': '+str(error))
    metrics={'python_tests_passed':data.get('python_tests'),'ui_tests_passed':data.get('ui-tests'),'desktop_tests_passed':data.get('desktop-tests'),
        'renderer_recovery_passed':data.get('renderer',{}).get('passed'),'fresh_runtime_idle':data.get('runtime',{}).get('idle'),
        'prompt_unchanged':data.get('runtime',{}).get('prompt_sha256')==plan['configuration']['prompt_sha256'],
        'household_memory_disabled':data.get('runtime',{}).get('memory_enabled') is False,
        'collection_errors':len(errors),'additional_api_usd':(ledger.used_micro_usd()-initial)/1e6,'elapsed_seconds':time.monotonic()-start}
    ledger.close();(folder/'observations.json').write_text(json.dumps({'metrics':metrics,'data':data,'errors':errors},indent=2)+'\n')
    artifacts=[p for p in folder.rglob('*') if p.is_file() and p.name not in ('run.json','protocol.json') and not set(p.relative_to(folder).parts)&{'source','context'}]
    r=finish(folder,metrics,artifacts=artifacts,completed=not errors,error=';'.join(errors) or None)
    report={'run':str(folder),'metrics':metrics,'decision':r['decision'],'audit':audit(folder),'data':data,'errors':errors,'critical_review':[
        'Current actual household/controller/canonical-context/native-text request and publication seams exercised with controlled identity, ranking, text and voice fixtures; no model usefulness or human/acoustic qualification.',
        'Native schema/document/vector recovery predecessor preserved. Current native inventory/worker/source packing helpers unchanged from that native run; later adapter changes type outages and harden local status/reprepare ownership.',
        'Actual Chromium/restricted bridge receives only a synthetic memory error. No positive supervision/processing choice, microphone request, playback, calibration or paid inference. Return-to-setup requires fresh choices and disables memory for the visit.',
        'All current code is loaded in fresh idle Mac core. HouseholdMemory.qualified remainsFalse; no threshold, bank, profile, prompt, model or budget activation.',
        'Real Hindsight retain/recall, ranking quality, natural response/learning behavior, long-running engine contention and physical drive/power-loss behavior still require separate evidence.'
    ]}
    number=plan['experiment_id'].rsplit('-',1)[1]
    (ROOT/f'docs/evaluations/paprika_household_integration_{number}.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'run':str(folder),'decision':r['decision']['outcome'],'metrics':metrics,'errors':errors}),flush=True)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--protocol');args=parser.parse_args();run(args.protocol)
