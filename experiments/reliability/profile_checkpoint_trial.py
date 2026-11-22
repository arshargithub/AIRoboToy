"""Owner-approved private Mac backup; exact candidate bytes, offline restore only."""
import io
import json
import os
from pathlib import Path
import unittest

from experiments.memory.runtime import ROOT
from experiments.reliability.mac_reliability_trial import status
from tavi.experiment_workflow import begin,finish,audit,discover_runs,read_protocol,digest
from tavi.identity_catalog import ProfileCatalog
from tavi.household_memory import HouseholdMemory
from tavi.profile_checkpoint import checkpoint,verify,restore_offline
from tavi.recovery_bundle import safe_path
from tavi.storage import Store


def run():
    os.umask(0o077);path=ROOT/'experiments/reliability/profile-checkpoint-protocol-v1.json';plan=read_protocol(path)
    if list((ROOT/'.tavi/experiments'/plan['experiment_id']).glob('*/run.json')):raise ValueError('No automatic repeat')
    prior=[audit(p.parent) for p in discover_runs()]
    catalogue=ProfileCatalog();catalogue.refresh();revision=catalogue.revision
    if revision!=plan['configuration']['profiles_revision']:raise ValueError('Reviewed candidate selection changed')
    destination=safe_path(ROOT/'.tavi/mac/recovery')
    if destination.stat().st_mode&0o077:raise ValueError('Private approved destination required')
    if destination.stat().st_dev==catalogue.root.stat().st_dev:raise ValueError('Separate storage required')
    before=status()
    if not before['idle'] or not before['family_off'] or HouseholdMemory.qualified:
        raise ValueError('Keep active session and calibration unchanged')
    folder,plan=begin(path);ledger=Store(ROOT/'.tavi/simulation/simulation.sqlite3',must_exist=True);used=ledger.used_micro_usd()
    data={};errors=[];tests=None;archive=None;restored=None
    try:
        stream=io.StringIO();tests=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromName('tests.test_profile_checkpoint'))
        (folder/'tests.log').write_text(stream.getvalue())
        if not tests.wasSuccessful():raise ValueError('Checkpoint controls failed')
        archive=checkpoint(catalogue,destination);value=verify(archive)
        restored=restore_offline(archive,destination);verify(restored)
        catalogue.refresh();after=status()
        data={'archive':str(archive),'offline_restore':str(restored),'profiles':len(value['files']),
              'profile_bytes':sum((archive/n).stat().st_size for n in value['files']),
              'same_bytes':all(digest(archive/n)==digest(restored/n)==digest(catalogue.entries[n[:-5]]['path'])==sha for n,sha in value['files'].items()),
              'profiles_revision':catalogue.revision,'originals_unchanged':catalogue.revision==revision,
              'private_modes':all(p.stat().st_mode&0o077==0 for root in (destination,archive,restored) for p in (root,*root.iterdir())),
              'separate_storage':destination.stat().st_dev!=catalogue.root.stat().st_dev,
              'offline_restore_marked':(restored/'RESTORE_VOICE_OFFLINE_ONLY.json').is_file(),
              'no_extra_payload':set(p.name for p in archive.iterdir())=={'manifest.json',*value['files']}
                    and set(p.name for p in restored.iterdir())=={'manifest.json','RESTORE_VOICE_OFFLINE_ONLY.json',*value['files']},
              'calibration_parked':after['family_off'] is True and not HouseholdMemory.qualified and not catalogue.status()['recognition_enabled'],
              'runtime_idle':after['idle'],'prompt_unchanged':after['prompt']==before['prompt'],
              'recognition_enabled':False,'authorizes_personal_memory':False}
    except Exception as e:errors.append(type(e).__name__+': '+str(e))
    metrics={k:data.get(k) for k in ('same_bytes','originals_unchanged','private_modes','separate_storage','offline_restore_marked','no_extra_payload','calibration_parked','runtime_idle','prompt_unchanged')}
    metrics.update(profiles=data.get('profiles'),tests_passed=tests.testsRun-len(tests.errors)-len(tests.failures) if tests else None,
                   additional_api_usd=(ledger.used_micro_usd()-used)/1e6,collection_errors=len(errors))
    ledger.close();(folder/'observations.json').write_text(json.dumps({'data':data,'metrics':metrics,'errors':errors},indent=2)+'\n')
    artifacts=[p for p in folder.rglob('*') if p.is_file() and p.name not in ('run.json','protocol.json') and not set(p.relative_to(folder).parts)&{'source','context'}]
    for root in (archive,restored):
        if root:artifacts.extend(p for p in root.iterdir() if p.is_file())
    record=finish(folder,metrics,artifacts=artifacts,completed=not errors,error='; '.join(errors) or None)
    report={'date':'2026-11-10 America/Toronto','run':str(folder),'metrics':metrics,'decision':record['decision'],'audit':audit(folder),'data':data,'errors':errors,
            'critical_review':['Owner explicitly approved10November copying four voice-profile JSON files to private Mac .tavi/mac/recovery; prior rejection is resolved by that specific approval.',
                               'Exact existing unqualified candidate bytes and clip metadata only. No raw recordings, credentials, model files, recognition policy or spend database copied.',
                               'One checkpoint and its marked offline restore verification remain inside the approved private destination. Original external profiles and selection are unchanged.',
                               'Source and destination are distinct mounted filesystems, matching the known external SSD and internal Mac locations. No physical device-failure test was performed.',
                               'The backup does not restore collection archives or qualify recognition. Calibration remains parked; copies cannot automatically select identity or enable personal memory.',
                               'No microphone, inference, prompt change, app restart or added API cost. No full E4/E5/E6 or household acceptance inferred.']}
    (ROOT/'docs/evaluations/paprika_profile_checkpoint_01.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'decision':record['decision']['outcome'],'metrics':metrics,'profile_bytes':data.get('profile_bytes'),'archive':str(archive) if archive else None,'errors':errors}),flush=True)


if __name__=='__main__':run()
