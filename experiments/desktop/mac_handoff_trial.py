"""Final local app handoff checks, without microphone/model/paid inference."""
import argparse
import json
from pathlib import Path
import plistlib
import subprocess
from experiments.memory.runtime import ROOT, SSD
from tavi.experiment_workflow import begin, audit, finish, digest
from tavi.storage import Store


def run(protocol='experiments/desktop/mac-handoff-protocol-v1.json', report_path='docs/evaluations/paprika_mac_desktop_handoff_01.json'):
    folder,_=begin(ROOT/protocol,run_root=SSD/'runs/scored');print(json.dumps(audit(folder)),flush=True)
    store=Store(ROOT/'.tavi/simulation/simulation.sqlite3');initial=store.used_micro_usd();store.close()
    commands=[['.venv-tavi/bin/python','-m','unittest','tests.test_mac_service','-v'],
        ['node','--test','tests/test_mac_audio_endpoint.cjs','tests/test_mac_check_guide.cjs','tests/test_mac_companion_ui.cjs','desktop/test/owner.test.cjs'],
        ['desktop/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron','desktop/test/smoke.cjs']]
    results=[]
    for n,cmd in enumerate(commands):
        result=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=30);output=result.stdout+result.stderr
        (folder/f'check-{n}.txt').write_text(output);results.append((result.returncode,output))
    bundle=ROOT/'.tavi/mac/build/Paprika-darwin-arm64/Paprika.app'
    plist=plistlib.loads((bundle/'Contents/Info.plist').read_bytes())
    script="""const fs=require('node:fs'),crypto=require('node:crypto'),asar=require('./desktop/node_modules/@electron/asar/lib/asar.js');const file='.tavi/mac/build/Paprika-darwin-arm64/Paprika.app/Contents/Resources/app.asar';let ok=true;for(const name of ['main.cjs','preload.cjs','owner.cjs'])ok=ok&&crypto.createHash('sha256').update(asar.extractFile(file,name)).digest('hex')===crypto.createHash('sha256').update(fs.readFileSync('desktop/'+name)).digest('hex');const config=JSON.parse(asar.extractFile(file,'development.json').toString());ok=ok&&config.projectRoot===process.cwd();console.log(JSON.stringify({matches:ok}));"""
    package=subprocess.run(['node','-e',script],cwd=ROOT,capture_output=True,text=True,timeout=10)
    matched=package.returncode==0 and json.loads(package.stdout)['matches']
    store=Store(ROOT/'.tavi/simulation/simulation.sqlite3');delta=(store.used_micro_usd()-initial)/1e6;store.close()
    metrics={'python_checks_passed':12 if results[0][0]==0 and 'Ran 12 tests' in results[0][1] else 0,
        'node_checks_passed':17 if results[1][0]==0 and 'pass 17' in results[1][1] else 0,
        'real_electron_setup_passed':results[2][0]==0 and 'Desktop smoke passed' in results[2][1],
        'bundle_matches_source':matched,'bundle_microphone_purpose_present':bool(plist.get('NSMicrophoneUsageDescription')),
        'test_failures':sum(c!=0 for c,_ in results)+int(package.returncode!=0),'real_microphone_used':False,'additional_api_usd':delta}
    observed={'metrics':metrics,'bundle':str(bundle),'bundle_identifier':plist['CFBundleIdentifier'],
        'app_asar_sha256':digest(bundle/'Contents/Resources/app.asar'),'ui_source_sha256':{str(p.relative_to(ROOT)):digest(p) for p in (ROOT/'tavi/web').glob('companion.*')},
        'synthetic_audio_reference':'docs/evaluations/paprika_mac_desktop_01.json','real_microphone':False}
    (folder/'observations.json').write_text(json.dumps(observed,indent=2)+'\n')
    (folder/'ui-smoke.json').write_bytes((ROOT/'.tavi/mac/ui-smoke.json').read_bytes())
    record=finish(folder,metrics,artifacts=list(folder.glob('check-*.txt'))+[folder/'observations.json',folder/'ui-smoke.json'],completed=True)
    report={**observed,'run':str(folder),'decision':record['decision'],'audit':audit(folder),'critical_review':[
        'This final screen is zero-inference engineering/packaging evidence. Earlier frozen synthetic-audio screen is separate; no real microphone or renewed acoustic acceptance is inferred.',
        'Actual renderer checks use untouched consent/processing choices; positive guide flows use fully controlled VM endpoint substitutes. Human adult feedback is unscored and does not pass original product gates.',
        'Optional feedback includes no microphone audio; last recognized exchange is saved only with explicit unchecked-by-default selection. The guide stops capture and requires a result before saving; failures/partial checks remain incomplete.',
        'Provider remains native text-only/anonymous/empty-memory. No family recognition, household learning, Pi LAN, login service, complete native backup or portable distribution is claimed.',
        'Human microphone permission/echo/barge-in/background/acoustic latency remain the next necessary checks. The app still depends on existing checkout/environments and external drive.'
    ]}
    (ROOT/report_path).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--protocol',default='experiments/desktop/mac-handoff-protocol-v1.json');parser.add_argument('--report',default='docs/evaluations/paprika_mac_desktop_handoff_01.json');args=parser.parse_args();run(args.protocol,args.report)
