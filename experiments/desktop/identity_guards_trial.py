"""Controlled guarded integration and complete calibration handoff screen."""
import json,plistlib,re,subprocess
from pathlib import Path
from experiments.memory.runtime import ROOT,SSD
from tavi.experiment_workflow import begin,audit,finish,digest,discover_runs,read_protocol
from tavi.storage import Store
from tavi.speaker_profile import VOICE


def run():
    # Fully finish the global checker and data-policy preflight before scoring.
    previous=[audit(p.parent) for p in discover_runs()]
    for name in ('calibration-capture','identity-heldout'):read_protocol(ROOT/f'experiments/speaker-id/{name}-protocol-v1.json')
    print(json.dumps({'preflight_runs_valid':len(previous),'complete':True}),flush=True)
    folder,_=begin(ROOT/'experiments/desktop/identity-guards-protocol-v1.json',run_root=SSD/'runs/scored');audit(folder)
    def balance():
        store=Store(ROOT/'.tavi/simulation/simulation.sqlite3',must_exist=True)
        try:return store.used_micro_usd()/1e6
        finally:store.close()
    initial=balance();visits_before=set((VOICE/'calibration').glob('*/visit.json'))
    electron='desktop/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron'
    commands=[['.venv-tavi/bin/python','-m','unittest','discover','-s','tests','-q'],
       ['node','--test','tests/test_mac_audio_endpoint.cjs','tests/test_mac_check_guide.cjs','tests/test_companion_state.cjs','tests/test_mac_companion_ui.cjs','desktop/test/owner.test.cjs'],
       ['node','tests/test_voice_calibration_ui.cjs'],[electron,'desktop/test/smoke.cjs'],[electron,'desktop/test/identity-smoke.cjs'],[electron,'desktop/test/audio-smoke.cjs']]
    results=[]
    for n,command in enumerate(commands):
        try:
            result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=85);code=result.returncode;out=result.stdout+result.stderr
        except subprocess.TimeoutExpired as error:code=124;out=str(error)
        (folder/f'check-{n}.txt').write_text(out);results.append((code,out));print(json.dumps({'check':n,'exit_code':code}),flush=True)
        if code:break # Preserve first failure; no handoff or automatic scored rerun.
    def passed(i,phrase):return len(results)>i and results[i][0]==0 and phrase in results[i][1]
    script="""const fs=require('node:fs'),crypto=require('node:crypto'),asar=require('./desktop/node_modules/@electron/asar/lib/asar.js');const file='.tavi/mac/build/Paprika-darwin-arm64/Paprika.app/Contents/Resources/app.asar';let ok=true;for(const n of ['main.cjs','preload.cjs','owner.cjs','package.json'])ok=ok&&crypto.createHash('sha256').update(asar.extractFile(file,n)).digest('hex')===crypto.createHash('sha256').update(fs.readFileSync('desktop/'+n)).digest('hex');console.log(JSON.stringify({matches:ok}));"""
    package=subprocess.run(['node','-e',script],cwd=ROOT,capture_output=True,text=True,timeout=10)
    bundle=ROOT/'.tavi/mac/build/Paprika-darwin-arm64/Paprika.app';plist=plistlib.loads((bundle/'Contents/Info.plist').read_bytes())
    match=re.search(r'Ran (\d+) tests',results[0][1]);metrics={'python_checks_passed':int(match[1]) if results[0][0]==0 and match else 0,
       'node_checks_passed':24 if passed(1,'pass 24') else 0,'guided_calibration_flows_passed':13 if passed(2,'13 guided flows passed') else 0,
       'actual_electron_ui_passed':passed(3,'Desktop smoke passed'),'actual_identity_navigation_passed':passed(4,'Identity desktop smoke passed'),
       'synthetic_audio_regression_passed':passed(5,'Synthetic microphone smoke passed'),
       'bundle_matches_source':package.returncode==0 and json.loads(package.stdout)['matches'],'bundle_version':plist['CFBundleShortVersionString'],
       'real_calibration_visits_created':len(set((VOICE/'calibration').glob('*/visit.json'))-visits_before),
       'test_failures':sum(code!=0 for code,_ in results),'real_microphone_used':False,'paid_inference_calls':0,'additional_api_usd':balance()-initial}
    artifacts=list(folder.glob('check-*.txt'))
    for name in ['identity-smoke.json','identity-overview.png','identity-settings.png','audio-smoke.json','ui-smoke.png']:
        p=ROOT/'.tavi/mac'/name
        if p.exists():target=folder/name;target.write_bytes(p.read_bytes());artifacts.append(target)
    observations={'metrics':metrics,'spent_or_reserved_usd':balance(),'candidate_people':['adultone','childtwo','childone'],'human_voice_evidence_collected':False,
       'identity_enabled':False,'household_memory_enabled':False,'E4_accepted':False,'E5_accepted':False}
    (folder/'observations.json').write_text(json.dumps(observations,indent=2)+'\n');artifacts.append(folder/'observations.json')
    sealed=finish(folder,metrics,artifacts=artifacts,completed=len(results)==len(commands))
    report={**observations,'run':str(folder),'decision':sealed['decision'],'audit':audit(folder),'critical_review':[
       'Controlled512d/voice-label fixtures and synthetic microphone test plumbing and guard behavior; no family recognition accuracy or caring-memory quality is inferred. Actual Electron negative consent creates no real calibration visit.',
       'Adult One enrollment reuses six independently saved historical owner-labelled sessions; all six sessions excluded from later heldout. A retrospective label and VAD quality do not prove sole-speaker purity. Candidates remain unqualified.',
       'Development-only thresholds cannot activate a profile. All four candidates, independent later reviewed25eligible/person,20unknown and20short/overlap controls are required for the individual screen; started heldout freezes further fit. A confident overlap result is evaluated normally and fails hypothetical memory authorization, never forced unknown by its label.',
       'Individual identity qualification still does not qualify group continuity/side conversations/closure or full E4. The new Hindsight canonical-source adapter is explicitly unqualified, so memory remains unavailable even after an individual identity pass. No final engine choice or household bank creation.',
       'Actual controller fixture checks accepted-current-speaker writes, uncertain-user abstention and retirement of previous personal history before anonymous routing. Native extraction/retrieval/restart and actual acoustic latency remain separate evidence.',
       'Source/model/profile hashes and strict-existing global ledger are bound. No endpoint/ASR/K/3sdeadline/800ms/prosody changes or saved-audio cloud upload. Same implementing author performed critical review; no independent reviewer is claimed.'
    ]}
    (ROOT/'docs/evaluations/paprika_identity_guards_01.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'report':'docs/evaluations/paprika_identity_guards_01.json','decision':sealed['decision'],'metrics':metrics}),flush=True)

if __name__=='__main__':run()
