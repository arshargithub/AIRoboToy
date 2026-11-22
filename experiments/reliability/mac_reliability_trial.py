"""No-inference reliability check; authored recovery sources and an idle Mac soak."""
import asyncio
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time

from experiments.memory.household_integration_trial import command as _command, STOP_IDLE, VERIFY
from experiments.memory.household_model_trial import wait_native_readiness
from experiments.memory.learning_queue import LearningQueue
from experiments.memory.runtime import ROOT, SSD, require_ssd
from tavi.experiment_workflow import begin, finish, audit, discover_runs, read_protocol
from tavi.identity_catalog import ProfileCatalog
from tavi.memory_generation import native_directory
from tavi.recovery_bundle import create_bundle, restore_bundle, rebuild_plan, verify_bundle
from tavi.storage import Store

def command(folder,name,args,**kwargs):
    try:return _command(folder,name,args,**kwargs)
    except subprocess.TimeoutExpired as error:
        (folder/(name+'.log')).write_bytes(error.stdout or b'')
        raise


STATUS=r"""
const {CoreOwner}=require('./desktop/owner.cjs');
(async()=>{const o=new CoreOwner(process.cwd());const s=await o.verify(o.read());const d=await o.request('/api/conversation/diagnostics');console.log(JSON.stringify({pid:o.record.pid,idle:d.lease_active===false,family_off:!s.family.family_voice_enabled&&!s.family.family_memory_requested&&!s.family.memory.ready,prompt:s.reply_prompt_sha256,budget:s.budget_usd,spent:s.spent_or_reserved_usd,ready:s.prerequisites.ready}));})().catch(e=>{console.error(e.message);process.exitCode=1;});
"""


def bundle_fixture(folder):
    root=folder/'fictional-bank';root.mkdir(mode=0o700);native_directory(root,source_realm='fixture')
    q=LearningQueue(root/'learning.sqlite3');ids=[]
    try:
        for i in range(12):
            scope={'session_id':'reliability-fiction','task':{'actual_speaker_id':'mira','people':{'mira':'Mira'},'audience_ids':['mira'],'conversation_at':'2026-11-09T12:00:00Z'}}
            ids.append(q.capture(scope,None,'An authored fictional event '+str(i),str(i))['source_id'])
            if i<8:q.complete(q.claim())
            elif i==8:
                job=q.claim();q.note_work(job,'dispatched');q.note_work(job,'ambiguous')
        q.revoke(ids[-1]);before=q.evidence_snapshot()
        bundle=create_bundle(root,folder,source_realm='fixture');verify_bundle(bundle)
        restored=restore_bundle(bundle,folder);plan=rebuild_plan(restored,current_queue=q.path)
        working=plan['status']=='needs_job_reconciliation' and len(plan['ambiguous_not_replayed'])==1
        q.revoke(ids[0]);stale=rebuild_plan(restored,current_queue=q.path)['status']=='stale_checkpoint'
        blocked=False
        try:other=LearningQueue(restored/'queue.sqlite3');other.close()
        except ValueError:blocked=True
        return {'bundle':str(bundle),'offline_restore':str(restored),'plan':plan,
                'source_count':len(before['records']),'ambiguity_preserved':working,'stale_restore_blocked':stale,
                'offline_activation_blocked':blocked,'original_ambiguity_not_replayed':q.working()==1}
    finally:q.close()


def status():
    result=subprocess.run(['node','-e',STATUS],cwd=ROOT,capture_output=True,text=True,timeout=10)
    if result.returncode:raise RuntimeError('Owned idle status unavailable')
    return json.loads(result.stdout)


def soak(folder,seconds,prompt,spent):
    start=time.monotonic();rows=[];last=None
    while True:
        began=time.monotonic();s=status();now=time.monotonic()
        resource=subprocess.run(['ps','-p',str(s['pid']),'-o','rss='],capture_output=True,text=True,timeout=3)
        rss=int(resource.stdout.strip());gap=0 if last is None else began-last
        row={'elapsed_seconds':now-start,'status_ms':(now-began)*1000,'gap_seconds':gap,'rss_kib':rss,
             'pid':s['pid'],'safe':s['idle'] and s['family_off'] and s['ready'] and s['budget']==31 and s['spent']==spent and s['prompt']==prompt}
        rows.append(row);last=began
        with (folder/'idle-samples.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
        if now-start>=seconds:break
        if len(rows)%12==1:print(json.dumps({'phase':'idle-soak','elapsed_seconds':round(now-start),'samples':len(rows),'safe':row['safe']}),flush=True)
        time.sleep(min(5,max(0,seconds-(time.monotonic()-start))))
    times=sorted(r['status_ms'] for r in rows);tail=max(1,len(rows)//5)
    growth=max(r['rss_kib'] for r in rows[-tail:])-max(r['rss_kib'] for r in rows[:tail])
    return {'elapsed_seconds':rows[-1]['elapsed_seconds'],'samples':len(rows),'all_idle_safe':all(r['safe'] for r in rows),
            'same_core':len({r['pid'] for r in rows})==1,'maximum_gap_seconds':max(r['gap_seconds'] for r in rows),
            'status_p95_ms':times[max(0,int(.95*len(times)+.999)-1)],'rss_growth_kib':growth,
            'note':'Real elapsed idle engineering soak. No live microphone, active inference/learning, physical sleep or eight-hour household acceptance.'}


def run(protocol_path=None):
    os.umask(0o077);require_ssd();protocol=Path(protocol_path) if protocol_path else ROOT/'experiments/reliability/mac-reliability-protocol-v1.json';plan=read_protocol(protocol)
    if list((SSD/'runs/scored'/plan['experiment_id']).glob('*/run.json')):raise ValueError('No automatic scored repeat')
    checks=[audit(p.parent) for p in discover_runs()];before=status()
    if not before['idle'] or not before['family_off']:raise ValueError('Active session: leave app intact')
    readiness=asyncio.run(wait_native_readiness());assert readiness['paid_enabled'] is False
    catalogue=ProfileCatalog();catalogue.refresh();revision=catalogue.revision
    folder,plan=begin(protocol,run_root=SSD/'runs/scored');print(json.dumps({'run':str(folder),'prior_valid':len(checks),'audit':audit(folder)}),flush=True)
    ledger=Store(ROOT/'.tavi/simulation/simulation.sqlite3',must_exist=True);initial=ledger.used_micro_usd();errors=[];data={}
    try:
        data['bundle']=bundle_fixture(folder)
        for name,args in [('python',[str(ROOT/'.venv-tavi/bin/python'),'-m','unittest','discover','-s','tests']),
                          ('ui',['node','--test','--test-reporter=tap',*map(str,sorted((ROOT/'tests').glob('*.cjs')))]),
                          ('desktop',['node','--test','--test-reporter=tap',*map(str,sorted((ROOT/'desktop/test').glob('*.test.cjs')))])]:
            out=command(folder,name,args);data[name]=int(re.search(r'Ran (\d+) tests' if name=='python' else r'# pass (\d+)',out).group(1))
        command(folder,'stop-idle',['node','-e',STOP_IDLE],timeout=40)
        env={**os.environ,'PAPRIKA_RELIABILITY_RENDERER_REPORT':str(folder/'renderer.json')}
        command(folder,'renderer',[str(ROOT/'desktop/node_modules/.bin/electron'),str(ROOT/'desktop/test/reliability-smoke.cjs')],env=env,timeout=45)
        data['renderer']=json.loads((folder/'renderer.json').read_text())
        command(folder,'reopen',['open',str(ROOT/'.tavi/mac/build/Paprika-darwin-arm64/Paprika.app')],timeout=10)
        data['runtime']=json.loads(command(folder,'fresh-runtime',['node','-e',VERIFY],timeout=30).strip())
        print(json.dumps({'phase':'regressions-and-renderer-passed','counts':{k:data[k] for k in ('python','ui','desktop')}}),flush=True)
        data['soak']=soak(folder,plan['configuration']['idle_soak_seconds'],plan['configuration']['prompt_sha256'],initial/1e6)
    except Exception as error:errors.append(type(error).__name__+': '+str(error))
    catalogue.refresh();native=asyncio.run(wait_native_readiness())
    bundle=data.get('bundle',{});s=data.get('soak',{})
    metrics={k:bundle.get(k) for k in ('ambiguity_preserved','stale_restore_blocked','offline_activation_blocked','original_ambiguity_not_replayed')}
    metrics.update(python_passed=data.get('python'),ui_passed=data.get('ui'),desktop_passed=data.get('desktop'),renderer_passed=data.get('renderer',{}).get('passed'),
                   soak_seconds=s.get('elapsed_seconds'),soak_samples=s.get('samples'),soak_all_idle_safe=s.get('all_idle_safe'),soak_same_core=s.get('same_core'),
                   maximum_gap_seconds=s.get('maximum_gap_seconds'),status_p95_ms=s.get('status_p95_ms'),rss_growth_kib=s.get('rss_growth_kib'),
                   profiles_unchanged=catalogue.revision==revision,paid_disabled=native['paid_enabled'] is False,
                   additional_api_usd=(ledger.used_micro_usd()-initial)/1e6,collection_errors=len(errors))
    ledger.close();(folder/'observations.json').write_text(json.dumps({'data':data,'metrics':metrics,'errors':errors},indent=2)+'\n')
    artifacts=[p for p in folder.rglob('*') if p.is_file() and p.name not in ('run.json','protocol.json') and not set(p.relative_to(folder).parts)&{'source','context'}]
    r=finish(folder,metrics,artifacts=artifacts,completed=not errors,error='; '.join(errors) or None)
    report={'date':'2026-11-10 America/Toronto','run':str(folder),'metrics':metrics,'decision':r['decision'],'audit':audit(folder),'data':data,'errors':errors,
            'limits':['Source-only backup/checkpoint and review plan, not a generated-index rebuild or live household restore. Native restore fixtures are separate prior evidence.',
                      'Actual renderer receives simulated power events; laptop never physically suspended and drive never disconnected.',
                      'Thirty-minute idle Mac engineering soak, not the planned eight-hour integrated household soak with active memory.',
                      'No real audio, profile modification, inference, budget increase, calibration or household activation. No product acceptance or memory-quality waiver.']}
    (ROOT/'docs/evaluations'/('paprika_'+plan['experiment_id'].lower().replace('-','_')+'.json')).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'run':str(folder),'decision':r['decision']['outcome'],'metrics':metrics,'errors':errors}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--protocol');args=parser.parse_args();run(args.protocol)
