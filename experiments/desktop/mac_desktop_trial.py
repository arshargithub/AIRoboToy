"""Frozen local Mac shell screen. No real input or paid provider inference."""
import json
from pathlib import Path
import subprocess
import time
from experiments.memory.runtime import ROOT, SSD, require_ssd
from tavi.experiment_workflow import begin, audit, finish
from tavi.storage import Store


def run():
    require_ssd()
    folder, plan = begin(ROOT/'experiments/desktop/mac-desktop-protocol-v1.json', run_root=SSD/'runs/scored')
    print(json.dumps(audit(folder)), flush=True)
    ledger=Store(ROOT/'.tavi/simulation/simulation.sqlite3'); initial=ledger.used_micro_usd(); ledger.close()
    commands=[['.venv-tavi/bin/python','-m','unittest','tests.test_mac_service','-v'],
              ['node','--test','tests/test_mac_audio_endpoint.cjs','desktop/test/owner.test.cjs'],
              ['desktop/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron','desktop/test/smoke.cjs'],
              ['desktop/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron','desktop/test/audio-smoke.cjs']]
    results=[];start=time.monotonic();error=None
    for n, command in enumerate(commands):
        try:
            result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=min(80,180-(time.monotonic()-start)))
            output=result.stdout+result.stderr;code=result.returncode
        except subprocess.TimeoutExpired as exc:
            output='Bounded subprocess timed out';code=-1;error=type(exc).__name__
        (folder/f'check-{n}.txt').write_text(output);results.append((code,output))
        if code:break
    ledger=Store(ROOT/'.tavi/simulation/simulation.sqlite3');delta=(ledger.used_micro_usd()-initial)/1e6;ledger.close()
    complete=len(results)==4
    audio_path=ROOT/'.tavi/mac/audio-smoke.json'
    audio=json.loads(audio_path.read_text()) if complete and audio_path.exists() else {}
    metrics={'python_checks_passed':9 if results[0][0]==0 and 'Ran 9 tests' in results[0][1] else 0,
             'node_checks_passed':11 if len(results)>1 and results[1][0]==0 and 'pass 11' in results[1][1] else 0,
             'real_electron_setup_passed':len(results)>2 and results[2][0]==0 and 'Desktop smoke passed' in results[2][1],
             'synthetic_audio_passed':complete and results[3][0]==0 and audio.get('completed') is True,
             'test_failures':sum(code!=0 for code,_ in results), 'real_microphone_used':False,'additional_api_usd':delta}
    for file in ('ui-smoke.json','audio-smoke.json'):
        if (ROOT/'.tavi/mac'/file).exists():(folder/file).write_bytes((ROOT/'.tavi/mac'/file).read_bytes())
    (folder/'observations.json').write_text(json.dumps({'metrics':metrics,'synthetic_audio':audio,'elapsed_seconds':time.monotonic()-start,'real_microphone':False},indent=2)+'\n')
    record=finish(folder,metrics,artifacts=list(folder.glob('check-*.txt'))+list(folder.glob('*smoke.json'))+[folder/'observations.json'],completed=complete and not error,error=error)
    report={'run':str(folder),'metrics':metrics,'decision':record['decision'],'audit':audit(folder),'critical_review':[
        'Controlled/fake microphone data and actual local-model startup are engineering evidence, not real microphone permission/acoustics, child voice or identity qualification.',
        'Same implementing author reviews the screen. No independent human acceptance, wake/interrupt accuracy, E3latency or E4/E5memory acceptance is inferred.',
        'New core reuses global spending ledger and existing models/controller; reasoning stays native text-only but generic anonymous conversations do not access memory or profile data.',
        'Development bundle remains tied to this Mac checkout/environments and SSD. Unsigned local prototype, no login agent or LAN exposure. No Pi pairing/transport implemented.',
        'Development diagnostics before this freeze preserved a port collision with unrelated8784service and a stylesheetCSP issue; both repaired before this run. Prior unrelated listener/family collection remain untouched.'
    ]}
    (ROOT/'docs/evaluations/paprika_mac_desktop_01.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)


if __name__=='__main__':run()
