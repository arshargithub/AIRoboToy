"""Frozen product UI and local goodbye regression screen; no real input/inference."""
import json
import plistlib
import subprocess
from experiments.memory.runtime import ROOT, SSD
from tavi.experiment_workflow import begin, audit, finish, digest
from tavi.storage import Store


def run():
    folder,_=begin(ROOT/'experiments/desktop/product-ui-protocol-v1.json',run_root=SSD/'runs/scored');print(json.dumps(audit(folder)),flush=True)
    ledger=ROOT/'.tavi/simulation/simulation.sqlite3';store=Store(ledger,must_exist=True);initial=store.used_micro_usd();store.close()
    commands=[['.venv-tavi/bin/python','-m','unittest','discover','-s','tests','-q'],
        ['node','--test','tests/test_mac_companion_ui.cjs','tests/test_companion_state.cjs','tests/test_mac_audio_endpoint.cjs','tests/test_mac_check_guide.cjs','desktop/test/owner.test.cjs'],
        ['desktop/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron','desktop/test/smoke.cjs'],
        ['desktop/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron','desktop/test/output-meter.cjs']]
    results=[]
    for n,cmd in enumerate(commands):
        result=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=40);out=result.stdout+result.stderr
        (folder/f'check-{n}.txt').write_text(out);results.append((result.returncode,out))
    script="""const fs=require('node:fs'),crypto=require('node:crypto'),asar=require('./desktop/node_modules/@electron/asar/lib/asar.js');const file='.tavi/mac/build/Paprika-darwin-arm64/Paprika.app/Contents/Resources/app.asar';let ok=true;for(const name of ['main.cjs','preload.cjs','owner.cjs'])ok=ok&&crypto.createHash('sha256').update(asar.extractFile(file,name)).digest('hex')===crypto.createHash('sha256').update(fs.readFileSync('desktop/'+name)).digest('hex');console.log(JSON.stringify({matches:ok}));"""
    bundle=ROOT/'.tavi/mac/build/Paprika-darwin-arm64/Paprika.app';check=subprocess.run(['node','-e',script],cwd=ROOT,capture_output=True,text=True,timeout=10)
    plist=plistlib.loads((bundle/'Contents/Info.plist').read_bytes())
    meter=json.loads((ROOT/'.tavi/mac/output-meter.json').read_text())
    store=Store(ledger,must_exist=True);delta=(store.used_micro_usd()-initial)/1e6;used=store.used_micro_usd()/1e6;store.close()
    metrics={'python_checks_passed':570 if results[0][0]==0 and 'Ran 570 tests' in results[0][1] else 0,
        'node_checks_passed':24 if results[1][0]==0 and 'pass 24' in results[1][1] else 0,
        'actual_electron_ui_passed':results[2][0]==0 and 'Desktop smoke passed' in results[2][1],
        'synthetic_output_meter_passed':results[3][0]==0 and meter['level']>0 and meter['afterMute']==0 and not meter['interruptedMarkedPlayed'],
        'bundle_matches_source':check.returncode==0 and json.loads(check.stdout)['matches'],
        'bundle_version':plist['CFBundleShortVersionString'],'test_failures':sum(code!=0 for code,_ in results)+int(check.returncode!=0),
        'real_microphone_used':False,'paid_inference_calls':0,'additional_api_usd':delta}
    screenshots=[]
    for name in ['ui-smoke.png']+['face-'+state+'.png' for state in ['standby','listening','thinking','talking','farewell','paused']]:
        target=folder/name;target.write_bytes((ROOT/'.tavi/mac'/name).read_bytes());screenshots.append(target)
    observed={'metrics':metrics,'spent_or_reserved_usd':used,'screenshots':{p.name:digest(p) for p in screenshots},'output_meter':meter,
        'goodbye_controls':{'direct_farewells':20,'nonclosing_cases':20,'controller_playback_before_close':True,'name_required_after_close':True},
        'owner_feedback':'Overall works well in quick test. Gaps/emphasis noted but examples unavailable; prosody explicitly deferred. Interface polish requested. No independent acoustic scoring inferred.'}
    (folder/'observations.json').write_text(json.dumps(observed,indent=2)+'\n')
    sealed=finish(folder,metrics,artifacts=screenshots+list(folder.glob('check-*.txt'))+[folder/'observations.json'],completed=True)
    report={**observed,'run':str(folder),'decision':sealed['decision'],'audit':audit(folder),'critical_review':[
        'Authored local farewells/negative cases are conservative development coverage, not proof of universal intent recognition. Unknown paraphrases retain ordinary model handling. No new classifier or extra cloud call.',
        'Goodbye ends active chat after acknowledged final audio, clears context and leaves local name listening running. It intentionally does not mute hardware. The new display distinguishes these states and shows Chat finished.',
        'Presentation screenshots use explicitly set view fixtures and allow CSS transitions to settle. They are visual/technical review only, not measured user-perceived state-recognition or acoustic latency. Runtime audio/state transitions are never artificially delayed.',
        'Output meter uses a synthetic in-memory Web Audio destination, no microphone or physical speakers. No raw recording, speech upload, K prosody/model/speed/800ms endpoint/3s age guard change.',
        'Same implementing author performs critical review. Original product gates remain open; owner quick-test feedback is qualitative. Existing identity embeddings are candidates, and Mac provider still uses anonymous empty-memory context with no learning.',
        'Development screenshot fixture initially had malformed generated JavaScript; corrected before this frozen screen. Existing recorded errors/reports are not overwritten. No family recording or private-memory data reused.'
    ]}
    (ROOT/'docs/evaluations/paprika_product_ui_01.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)


if __name__=='__main__':run()
