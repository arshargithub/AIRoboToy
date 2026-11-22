"""Bounded package-check repair; runtime source and passed controls unchanged."""
import json,subprocess
from experiments.memory.runtime import ROOT,SSD
from tavi.experiment_workflow import begin,audit,finish,digest,discover_runs
from tavi.storage import Store


def run():
    for p in discover_runs():audit(p.parent)
    previous=json.loads((ROOT/'docs/evaluations/paprika_identity_guards_01.json').read_text());old=json.loads((__import__('pathlib').Path(previous['run'])/'run.json').read_text())
    unchanged=all(digest(ROOT/name)==sha for name,sha in old['source_sha256'].items())
    if not unchanged:raise ValueError('Runtime/source drift: cannot reuse passed controls')
    folder,_=begin(ROOT/'experiments/desktop/identity-handoff-protocol-v1.json',run_root=SSD/'runs/scored');audit(folder)
    def balance():
        store=Store(ROOT/'.tavi/simulation/simulation.sqlite3',must_exist=True)
        try:return store.used_micro_usd()/1e6
        finally:store.close()
    initial=balance()
    script="""const fs=require('node:fs'),crypto=require('node:crypto'),assert=require('node:assert/strict'),asar=require('./desktop/node_modules/@electron/asar/lib/asar.js');const f='.tavi/mac/build/Paprika-darwin-arm64/Paprika.app/Contents/Resources/app.asar';for(const n of ['main.cjs','preload.cjs','owner.cjs'])assert(asar.extractFile(f,n).equals(fs.readFileSync('desktop/'+n)),n+' mismatch');const expected=JSON.parse(fs.readFileSync('desktop/package.json'));for(const k of ['private','scripts','devDependencies'])delete expected[k];const packed=JSON.parse(asar.extractFile(f,'package.json'));assert.deepEqual(packed,expected);assert.equal(packed.version,'0.3.0');const dev=JSON.parse(asar.extractFile(f,'development.json'));assert.equal(dev.projectRoot,process.cwd());console.log('Package verification passed: executable bytes, complete expected pruned metadata, version and project binding.');"""
    checks=[]
    for n,command in enumerate([['node','-e',script],['desktop/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron','desktop/test/identity-smoke.cjs']]):
        r=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=40);out=r.stdout+r.stderr;(folder/f'check-{n}.txt').write_text(out);checks.append((r.returncode,out))
        if r.returncode:break
    metrics={'prior_runtime_sources_unchanged':unchanged,'prior_python_checks_passed':previous['metrics']['python_checks_passed'],
        'prior_node_checks_passed':previous['metrics']['node_checks_passed'],'prior_guided_flows_passed':previous['metrics']['guided_calibration_flows_passed'],
        'package_verification_passed':checks[0][0]==0 and 'Package verification passed' in checks[0][1],
        'actual_identity_navigation_passed':len(checks)==2 and checks[1][0]==0 and 'Identity desktop smoke passed' in checks[1][1],
        'test_failures':sum(code!=0 for code,_ in checks),'additional_api_usd':balance()-initial}
    report={'metrics':metrics,'prior_screen':previous['run'],'prior_overall_decision':'fail','prior_failure':'Overstrict metadata check included intentionally pruned private/scripts/devDependencies. All3 executable files matched; metadata repair compares complete expected pruned object, not only version.',
        'spent_or_reserved_usd':balance(),'identity_enabled':False,'household_memory_enabled':False,'E4_accepted':False,'E5_accepted':False,
        'critical_review':['No runtime source, models, decision cutoffs or human data changed. Original failed screen preserved. Reused621Python/24Node/13guided-flow controls apply only to identical source hashes; new actual Electron IPC/navigation and exact package inspection pass independently.',
            'Prototype engineering handoff only; no human voice accuracy, group interaction, memory semantic quality or product acceptance. Candidate voices remain disabled and the new household adapter remains unqualified.',
            'Packager pruning is explicitly enumerated and all remaining metadata keys/values must match; no wildcard omission or weakened executable comparison.']}
    (folder/'observations.json').write_text(json.dumps(report,indent=2)+'\n')
    sealed=finish(folder,metrics,artifacts=[folder/'observations.json']+list(folder.glob('check-*.txt')),completed=len(checks)==2)
    report.update(run=str(folder),decision=sealed['decision'],audit=audit(folder))
    (ROOT/'docs/evaluations/paprika_identity_handoff_01.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'decision':sealed['decision'],'report':'docs/evaluations/paprika_identity_handoff_01.json'}),flush=True)

if __name__=='__main__':run()
