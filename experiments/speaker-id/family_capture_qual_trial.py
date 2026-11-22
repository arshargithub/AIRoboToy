"""Synthetic qualification only, never supplies real family voice consent."""
import argparse
import io
import json
from pathlib import Path
import subprocess
import time
import unittest
from experiments.memory.runtime import ROOT,SSD,require_ssd
from tavi.experiment_workflow import begin,audit,finish,digest
from tavi.family_capture import ready
from tavi.storage import Store


def human_runs():return len(list((SSD/'runs/scored/FAMILY-VOICE-COLLECTION-01').glob('*/run.json')))


def run(protocol='experiments/speaker-id/family-capture-qual-protocol-v1.json',report_path='docs/evaluations/paprika_family_capture_qual_01.json'):
    require_ssd();folder,plan=begin(ROOT/protocol,run_root=SSD/'runs/scored')
    print(json.dumps(audit(folder)),flush=True)
    cfg=json.loads((ROOT/'experiments/speaker-id/family-capture-qual-input-v1.json').read_text())
    ledger=Store(ROOT/'.tavi/simulation/simulation.sqlite3');initial=ledger.used_micro_usd();before=human_runs();start=time.monotonic();errors=[]
    stream=io.StringIO();suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromName(m) for m in cfg['python_modules']])
    tests=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite);(folder/'python-tests.txt').write_text(stream.getvalue())
    outputs={}
    for key in ('javascript_family','javascript_workshop'):
        result=subprocess.run(['node',cfg[key]],cwd=ROOT,text=True,capture_output=True,timeout=15)
        (folder/(key+'.txt')).write_text(result.stdout+result.stderr);outputs[key]=result
    try:ready();model_ready=True
    except Exception as error:model_ready=False;errors.append(type(error).__name__)
    manifest=json.loads((ROOT/'experiments/speaker-id/family-prompt-audio-assets-v1.json').read_text())
    prompt_count=sum(digest(p['path'])==p['sha256'] for p in manifest['prompts'])
    if time.monotonic()-start>plan['limits']['maximum_wall_seconds']:errors.append('wall_limit')
    family=outputs['javascript_family'];workshop=outputs['javascript_workshop']
    metrics={'python_checks_passed':tests.testsRun-len(tests.failures)-len(tests.errors),
        'family_javascript_flows_passed':8 if family.returncode==0 and '8 flows pass' in family.stdout else 0,
        'workshop_javascript_passed':workshop.returncode==0,
        'test_failures':len(tests.failures)+len(tests.errors)+int(family.returncode!=0)+int(workshop.returncode!=0),
        'local_model_environment_ready':model_ready,'prompt_assets_verified':prompt_count,'real_family_runs_created':human_runs()-before,
        'collection_errors':len(errors),'additional_api_usd':(ledger.used_micro_usd()-initial)/1e6}
    ledger.close();(folder/'observations.json').write_text(json.dumps({'metrics':metrics,'errors':errors,'human_consent_supplied':False,'real_recording':False},indent=2)+'\n')
    artifacts=[folder/'python-tests.txt',folder/'javascript_family.txt',folder/'javascript_workshop.txt',folder/'observations.json']
    sealed=finish(folder,metrics,artifacts=artifacts,completed=not errors,error=';'.join(errors) or None)
    report={'run':str(folder),'metrics':metrics,'decision':sealed['decision'],'audit':audit(folder),'critical_review':[
        'Synthetic512dmodel/PCM/storage/capture substitutes and temporary consent fixtures establish control/persistence semantics, not actual human consent, acoustic identity, overlap detection, child enjoyment or E4acceptance.',
        'New supervised-family policy is separate from adult-only trials: guardian/ownvoice, willingness, onevoice, no cloud and retention are explicit. Agent never opens real microphone or checks positive human choices.',
        'Subject-specific URL/browser keys/token binding stop accidental cross-person file attribution. Names and parent labels are trusted inputs, not biometric proof; actual voice quality and same-family confusion need later held-out evaluation.',
        'Short/quiet/clipped/duplicate/interrupted samples do not become eligible; fresh questions progress the story. Technical errors retain current PCM for retry while page remains open; an unfinished unsaved recording cannot survive a tab close and can be skipped without losing earlier useful examples.',
        'Optional provisional reference audio is private local data. Explicit review exclusions remove vector and discard provisional raw; interrupted cleanup remains blocked/retryable. No physical secure-erasure, backup derivative or unknown-speaker certification claimed.',
        'Twositting/12persitting/24total and atmost2newprofiles/persubject bound this collection; six reviewed examples create only candidate_unqualified with null threshold and no personal-memory authority. Pause/incomplete is not passed recognition.',
        'CachedKquestion assets passed separate local format/hash screen. Playback stops before microphone setup/countdown, but no actual echo/acoustic timing or intelligibility acceptance inferred. Local real-model environment checked without inference here.',
        'Workshop can explicitly start only known local preparation modules; ready links are not live companion qualification. All data remains local; no model/voice/800msendpoint/identity threshold, paid API or data-destination change.'
    ]}
    (ROOT/report_path).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--protocol',default='experiments/speaker-id/family-capture-qual-protocol-v1.json');parser.add_argument('--report',default='docs/evaluations/paprika_family_capture_qual_01.json');args=parser.parse_args()
    run(args.protocol,args.report)
