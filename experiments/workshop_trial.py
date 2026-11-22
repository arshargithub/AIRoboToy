"""Zero-paid workshop guard screen; preserves existing local setup servers."""
import io
import json
import subprocess
import time
import unittest
from experiments.memory.runtime import ROOT,SSD,require_ssd
from tavi.experiment_workflow import begin,audit,finish
from tavi.storage import Store
from tavi.workshop import PreviewOwner,status


def run():
    require_ssd();folder,plan=begin(ROOT/'experiments/workshop-protocol-v1.json',run_root=SSD/'runs/scored')
    print(json.dumps(audit(folder)),flush=True)
    cfg=json.loads((ROOT/'experiments/workshop-input-v1.json').read_text())
    ledger=Store(ROOT/'.tavi/simulation/simulation.sqlite3');initial=ledger.used_micro_usd()
    start=time.monotonic();stream=io.StringIO();errors=[]
    tests=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromName(cfg['python_module']))
    (folder/'python-tests.txt').write_text(stream.getvalue())
    js=subprocess.run(['node',cfg['javascript']],cwd=ROOT,text=True,capture_output=True,timeout=10)
    (folder/'javascript.txt').write_text(js.stdout+js.stderr)
    launches=[]
    def forbidden(*args,**kwargs):launches.append(True);raise RuntimeError('Existing service must not be spawned')
    owner=PreviewOwner(popen=forbidden);preserved=False
    try:preserved=all(owner.ensure(name)['recognized'] for name in cfg['existing_service_keys']) and not owner.children and not launches
    except Exception as error:errors.append(type(error).__name__+': '+str(error))
    finally:owner.close()
    if time.monotonic()-start>plan['limits']['maximum_wall_seconds']:errors.append('wall_limit')
    metrics={'python_checks_passed':tests.testsRun-len(tests.failures)-len(tests.errors),'javascript_passed':js.returncode==0,
        'test_failures':len(tests.failures)+len(tests.errors)+int(js.returncode!=0),'existing_services_preserved_without_spawn':preserved,
        'collection_errors':len(errors),'additional_api_usd':(ledger.used_micro_usd()-initial)/1e6}
    ledger.close();(folder/'observations.json').write_text(json.dumps({'metrics':metrics,'errors':errors,'read_only_live_status':status(),'model_inference':False},indent=2)+'\n')
    sealed=finish(folder,metrics,artifacts=[folder/'python-tests.txt',folder/'javascript.txt',folder/'observations.json'],completed=not errors,error=';'.join(errors) or None)
    report={'run':str(folder),'metrics':metrics,'decision':sealed['decision'],'audit':audit(folder),'critical_review':[
        'Preparation hub only, not a unified live companion. Ready setup endpoints/file presence do not establish loaded models, acoustic quality, speaker identity, selected memory engine or household acceptance.',
        'Python tests use controlled child handles and actual local HTTP fixtures; actual live probe deliberately forbids spawning and verifies existing preview endpoints preserved. No real missing-service child startup/active-recording shutdown endurance is qualified by this screen.',
        'Explicit same-origin action can start only known local adult/adventure servers. Their own consent gates remain necessary; startup itself starts no microphone/native model/paid memory job. Existing/foreign occupied processes are never replaced or stopped.',
        'Budget query opens existing SQLite read-only and returns aggregate conservative spending only. No credentials, source texts, voice files or personal embeddings are loaded by health status. No automatic budget restoration/paid retry.',
        'Loopback probes disable proxies/redirects and use fixed expected component shapes; they are readiness screens, not cryptographic service authentication. A slow/unverified occupied port remains untouched.',
        'Actual UI JS traps prohibited capabilities and tests refresh/prepare/failure recovery, missing drive/ledger and unsafe URL suppression. Browser review remains separate; no new recording or human acceptance inferred.'
    ]}
    (ROOT/'docs/evaluations/paprika_workshop_readiness_01.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)


if __name__=='__main__':run()
