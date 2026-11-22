"""Final no-inference checks after the stop-only IPC deadline change."""
import asyncio
import json
import os
from pathlib import Path
import re
from experiments.memory.household_integration_trial import STOP_IDLE, VERIFY
from experiments.memory.household_model_trial import wait_native_readiness
from experiments.memory.runtime import ROOT,SSD,require_ssd
from experiments.reliability.mac_reliability_trial import command,status
from tavi.experiment_workflow import begin,finish,audit,discover_runs,read_protocol
from tavi.identity_catalog import ProfileCatalog
from tavi.storage import Store


def run():
    os.umask(0o077);require_ssd();protocol=ROOT/'experiments/reliability/stop-deadline-protocol-v1.json';plan=read_protocol(protocol)
    if list((SSD/'runs/scored'/plan['experiment_id']).glob('*/run.json')):raise ValueError('No automatic repeat')
    prior=[audit(p.parent) for p in discover_runs()];before=status()
    if not before['idle'] or not before['family_off']:raise ValueError('Active user session left intact')
    predecessor=json.loads((ROOT/'docs/evaluations/paprika_mac_reliability_02.json').read_text())
    if predecessor['decision']['outcome']!='pass':raise ValueError('Preserve earlier failed screen')
    folder,plan=begin(protocol,run_root=SSD/'runs/scored');store=Store(ROOT/'.tavi/simulation/simulation.sqlite3',must_exist=True);used=store.used_micro_usd()
    data={};errors=[];catalog=ProfileCatalog();catalog.refresh();revision=catalog.revision
    try:
        for name,args in [('python',[str(ROOT/'.venv-tavi/bin/python'),'-m','unittest','discover','-s','tests']),
                          ('ui',['node','--test','--test-reporter=tap',*map(str,sorted((ROOT/'tests').glob('*.cjs')))]),
                          ('desktop',['node','--test','--test-reporter=tap',*map(str,sorted((ROOT/'desktop/test').glob('*.test.cjs')))])]:
            out=command(folder,name,args);data[name]=int(re.search(r'Ran (\d+) tests' if name=='python' else r'# pass (\d+)',out).group(1))
        command(folder,'stop-idle',['node','-e',STOP_IDLE],timeout=40)
        command(folder,'build',['node','desktop/build.cjs'],timeout=120)
        verify_bundle=r"const fs=require('node:fs'),a=require('./desktop/node_modules/@electron/asar/lib/asar.js');for(const n of ['owner.cjs','main.cjs']){if(!a.extractFile('.tavi/mac/build/Paprika-darwin-arm64/Paprika.app/Contents/Resources/app.asar',n).equals(fs.readFileSync('desktop/'+n)))throw Error('Bundle mismatch');}console.log('Bundled main/owner exactly match current source');"
        command(folder,'bundle-match',['node','-e',verify_bundle]);data['bundle_matches']=True
        env={**os.environ,'PAPRIKA_RELIABILITY_RENDERER_REPORT':str(folder/'renderer.json')}
        command(folder,'renderer',[str(ROOT/'desktop/node_modules/.bin/electron'),str(ROOT/'desktop/test/reliability-smoke.cjs')],env=env,timeout=45)
        data['renderer']=json.loads((folder/'renderer.json').read_text())
        command(folder,'reopen',['open',str(ROOT/'.tavi/mac/build/Paprika-darwin-arm64/Paprika.app')],timeout=10)
        data['runtime']=json.loads(command(folder,'fresh-runtime',['node','-e',VERIFY],timeout=30))
        data['native']=asyncio.run(wait_native_readiness());catalog.refresh()
    except Exception as e:errors.append(type(e).__name__+': '+str(e))
    metrics={'python_passed':data.get('python'),'ui_passed':data.get('ui'),'desktop_passed':data.get('desktop'),
             'bundle_matches':data.get('bundle_matches'),'renderer_passed':data.get('renderer',{}).get('passed'),
             'runtime_idle':data.get('runtime',{}).get('idle'),'prompt_unchanged':data.get('runtime',{}).get('prompt_sha256')==plan['configuration']['prompt_sha256'],
             'profiles_unchanged':catalog.revision==revision,'additional_api_usd':(store.used_micro_usd()-used)/1e6,'collection_errors':len(errors)}
    store.close();(folder/'observations.json').write_text(json.dumps({'data':data,'metrics':metrics,'errors':errors},indent=2)+'\n')
    artifacts=[p for p in folder.rglob('*') if p.is_file() and p.name not in ('run.json','protocol.json') and not set(p.relative_to(folder).parts)&{'source','context'}]
    r=finish(folder,metrics,artifacts=artifacts,completed=not errors,error='; '.join(errors) or None)
    report={'date':'2026-11-10 America/Toronto','run':str(folder),'metrics':metrics,'decision':r['decision'],'audit':audit(folder),'data':data,'errors':errors,
            'limits':['Only stop IPC deadline changed25s to2.5s; other commands, silence endpoint, voice and prompt unchanged.',
                      'Actual stalled local transport verified at the IPC-configured deadline; no real microphone or provider request.',
                      'Prior30-minute idle engineering soak applies to idle behavior before this stop-only change; no eight-hour household/product acceptance inferred.',
                      'Profile checkpoint tests use authored fake vectors only. No actual biometric backup without pending explicit approval.']}
    (ROOT/'docs/evaluations/paprika_stop_deadline_01.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'run':str(folder),'decision':r['decision']['outcome'],'metrics':metrics,'errors':errors}),flush=True)


if __name__=='__main__':run()
