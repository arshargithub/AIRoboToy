"""Freeze experiment evidence and evaluate engineering screens, never product acceptance.

No model, microphone, network or paid provider is invoked by this module.
Runs are private because input manifests can identify saved recordings.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = {'experiment_id','work_item','hypothesis','configuration','inputs',
            'criteria','limits','data_policy','next_actions','source_paths'}


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def read_protocol(path):
    plan=json.loads(Path(path).read_text())
    if not REQUIRED <= plan.keys():raise ValueError('Incomplete experiment protocol')
    if not re.fullmatch(r'[A-Z][A-Z0-9_-]{2,63}',plan['experiment_id']):
        raise ValueError('Invalid experiment ID')
    if not plan['criteria'] or not plan['inputs'] or not plan['source_paths']:
        raise ValueError('Criteria, inputs and source bindings are required')
    if plan['data_policy'] not in ('saved_audio_local','synthetic_audio_openai','fictional_text_only','new_adult_audio_consent','new_supervised_family_audio_consent','new_voice_calibration_consent'):
        raise ValueError('Unrecognized data scope; explicit policy review required')
    for criterion in plan['criteria']:
        if not isinstance(criterion.get('metric'),str) or not any(k in criterion for k in ('min','max','equals')):
            raise ValueError('Every screen criterion needs a metric and bound')
    limit=plan['limits'].get('maximum_additional_api_usd')
    if isinstance(limit,bool) or not isinstance(limit,(int,float)) or not math.isfinite(limit) or not 0<=limit<=25:
        raise ValueError('Explicit bounded API budget required')
    if plan['data_policy']=='saved_audio_local' and limit!=0:
        raise ValueError('Local saved-audio run cannot authorize API spending')
    if plan['data_policy']=='new_supervised_family_audio_consent' and limit!=0:
        raise ValueError('Family voice collection is local-only and cannot authorize paid requests')
    if plan['data_policy']=='new_voice_calibration_consent' and limit!=0:
        raise ValueError('Voice calibration is local-only and cannot authorize paid requests')
    if not all(k in plan['next_actions'] for k in ('pass','fail','needs_evidence','error')):
        raise ValueError('Every outcome requires a next action')
    return plan


def source_path(relative):
    path=ROOT/relative
    if path.is_symlink():raise ValueError('Source snapshots cannot follow symlinks')
    resolved=path.resolve();resolved.relative_to(ROOT.resolve())
    if relative not in ('AGENTS.md','pyproject.toml','uv.lock') and not relative.startswith(('tavi/','tests/','experiments/','docs/','desktop/')):
        raise ValueError('Only explicit project source/configuration can be snapshotted')
    if any(part.startswith('.') for part in Path(relative).parts):
        raise ValueError('Hidden/private files cannot be source snapshots')
    return path


def begin(protocol_path, *, run_root=None, consent=None):
    protocol_path=Path(protocol_path);plan=read_protocol(protocol_path)
    active_plan=ROOT/'docs/PAPRIKA_EXECUTION_PLAN.md'
    if not active_plan.exists():raise ValueError('Read and persist an active execution plan before a scored run')
    work_items=re.findall(r'^\|\s*([A-Z][0-9])\s*\|',active_plan.read_text(),re.M)
    if plan['work_item'] not in work_items:raise ValueError('Experiment work item is not in the active plan')
    if plan['data_policy']=='new_adult_audio_consent':
        if (not isinstance(consent,dict) or consent.get('adult') is not True
                or consent.get('recording') is not True or type(consent.get('cloud')) is not bool):
            raise ValueError('New adult collection requires explicit recording and destination choices')
    if plan['data_policy']=='new_supervised_family_audio_consent':
        if (not isinstance(consent,dict) or consent.get('adult') is not True or consent.get('recording') is not True
                or consent.get('cloud') is not False or consent.get('processing')!='local-only'
                or consent.get('subject_id') not in ('childone','childtwo','adulttwo')
                or type(consent.get('subject_is_child')) is not bool
                or consent['subject_is_child']!=(consent['subject_id'] in ('childone','childtwo'))
                or consent.get('subject_willing') is not True or consent.get('alone') is not True
                or type(consent.get('retain_audio')) is not bool
                or (consent['subject_is_child'] and consent.get('supervised') is not True)
                or (not consent['subject_is_child'] and consent.get('own_voice') is not True)):
            raise ValueError('Fresh local family collection requires explicit adult supervision or own voice, willingness and retention choices')
    if plan['data_policy']=='new_voice_calibration_consent':
        if (not isinstance(consent,dict) or consent.get('adult') is not True or consent.get('recording') is not True
                or consent.get('cloud') is not False or consent.get('processing')!='local-only'
                or consent.get('subject_id') not in ('adultone','adulttwo','childtwo','childone','guest','short','overlap')
                or consent.get('phase') not in ('development','heldout')
                or (consent.get('subject_id') in ('short','overlap') and consent.get('phase')!='heldout')
                or consent.get('subject_willing') is not True
                or (consent['subject_id']!='overlap' and consent.get('alone') is not True)
                or (consent['subject_id']=='overlap' and (consent.get('alone') is not False or consent.get('two_speakers_agree') is not True))
                or type(consent.get('retain_audio')) is not bool
                or (consent['subject_id'] in ('childtwo','childone','overlap') and consent.get('supervised') is not True)
                or (consent['subject_id'] not in ('childtwo','childone','overlap') and consent.get('own_voice') is not True)
                or (consent['subject_id']=='guest' and consent.get('outside_family') is not True)
                or (consent['phase']=='heldout' and consent.get('different_occasion') is not True)):
            raise ValueError('Fresh voice checking needs explicit supervision/own voice, phase, local processing and retention choice')
    # Check everything before making a partial run directory.
    sources={p:digest(source_path(p)) for p in plan['source_paths']}
    inputs={p:digest(ROOT/p) for p in plan['inputs']}
    for manifest_path in plan.get('input_manifests',[]):
        if manifest_path not in plan['inputs']:raise ValueError('Input manifest must itself be bound')
        for info in json.loads((ROOT/manifest_path).read_text())['files']:
            sha=digest(ROOT/info['path'])
            if sha!=info['sha256']:raise ValueError('Manifest input file changed')
            inputs[info['path']]=sha
    run_root=Path(run_root) if run_root else ROOT/'.tavi/experiments'
    folder=run_root/plan['experiment_id']/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder.mkdir(parents=True,mode=0o700,exist_ok=False)
    (folder/'protocol.json').write_bytes(protocol_path.read_bytes())
    for name,sha in sources.items():
        destination=folder/'source'/name;destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes(source_path(name).read_bytes())
        if digest(destination)!=sha:raise ValueError('Source changed during snapshot')
    context={}
    for name in ['docs/PAPRIKA_EXECUTION_PLAN.md','AGENTS.md']:
        if not (ROOT/name).exists():continue
        target=folder/'context'/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((ROOT/name).read_bytes());context[name]=digest(target)
    record={'schema_version':2,'experiment_id':plan['experiment_id'],'work_item':plan['work_item'],
            'began_utc':datetime.now(timezone.utc).isoformat(),'protocol_sha256':digest(folder/'protocol.json'),
            'source_sha256':sources,'input_sha256':inputs,'plan_context_sha256':context,'state':'running',
            'execution_completed':False,'screen_passed':False,'integration_qualified':False,
            'product_accepted':False}
    if consent is not None:record['consent']=consent
    (folder/'run.json').write_text(json.dumps(record,indent=2)+'\n')
    return folder,plan


def evaluate(plan,metrics,*,completed=True,error=None):
    checks=[]
    for rule in plan['criteria']:
        value=metrics.get(rule['metric']);known=value is not None
        if isinstance(value,float) and not math.isfinite(value):known=False
        passed=known
        if passed and 'equals' in rule:passed=value==rule['equals'] and type(value)==type(rule['equals'])
        for key,comparison in [('min',lambda a,b:a>=b),('max',lambda a,b:a<=b)]:
            if passed and key in rule:
                passed=isinstance(value,(int,float)) and not isinstance(value,bool) and comparison(value,rule[key])
        checks.append({'metric':rule['metric'],'value':value,'known':known,'passed':bool(passed)})
    outcome=('error' if error or not completed else
             'fail' if any(c['known'] and not c['passed'] for c in checks) else
             'needs_evidence' if any(not c['known'] for c in checks) else 'pass')
    return {'outcome':outcome,'checks':checks,'next_action':plan['next_actions'][outcome]}


def finish(folder,metrics,*,artifacts=(),completed=True,error=None):
    folder=Path(folder);record=json.loads((folder/'run.json').read_text())
    if record['state']!='running':raise ValueError('Finished experiment is immutable; begin a new run')
    if digest(folder/'protocol.json')!=record['protocol_sha256']:raise ValueError('Frozen protocol changed')
    for name,sha in record['source_sha256'].items():
        if digest(folder/'source'/name)!=sha or digest(source_path(name))!=sha:
            raise ValueError('Experiment source changed; do not misbind results')
    for name,sha in record['input_sha256'].items():
        if digest(ROOT/name)!=sha:raise ValueError('Experiment inputs changed')
    plan=read_protocol(folder/'protocol.json')
    result=evaluate(plan,metrics,completed=completed,error=error)
    record.update(state='finished',ended_utc=datetime.now(timezone.utc).isoformat(),
                  execution_completed=bool(completed and not error),metrics=metrics,
                  screen_passed=result['outcome']=='pass',decision=result,
                  artifacts={str(Path(p).resolve()):digest(p) for p in artifacts},error=error)
    (folder/'run.json').write_text(json.dumps(record,indent=2,allow_nan=False)+'\n')
    return record


def audit(folder):
    folder=Path(folder);record=json.loads((folder/'run.json').read_text())
    if digest(folder/'protocol.json')!=record['protocol_sha256']:raise ValueError('Protocol hash mismatch')
    for name,sha in record['source_sha256'].items():
        if digest(folder/'source'/name)!=sha:raise ValueError('Source snapshot hash mismatch')
    for name,sha in record.get('plan_context_sha256',{}).items():
        if digest(folder/'context'/name)!=sha:raise ValueError('Active plan context hash mismatch')
    for name,sha in record.get('artifacts',{}).items():
        if digest(name)!=sha:raise ValueError('Result artifact hash mismatch')
    if record['state']=='finished':
        expected=evaluate(read_protocol(folder/'protocol.json'),record['metrics'],
                          completed=record['execution_completed'],error=record['error'])
        if expected!=record['decision'] or record['screen_passed']!=(expected['outcome']=='pass'):
            raise ValueError('Decision does not match frozen criteria')
    if record['integration_qualified'] or record['product_accepted']:
        raise ValueError('A component screen cannot grant integration or product acceptance')
    return {'experiment_id':record['experiment_id'],'state':record['state'],
            'decision':record.get('decision',{}).get('outcome'),'valid':True}


def discover_runs():
    """Include the explicitly configured external memory evidence store.

    An unplugged drive must not silently turn the memory audit into an empty
    successful check. No remote storage or neighboring project is discovered.
    """
    folders=list((ROOT/'.tavi/experiments').glob('*/*/run.json'))
    pointer=ROOT/'.tavi/memory-runtime.json'
    if pointer.exists():
        if pointer.stat().st_size>4096:raise ValueError('Invalid memory runtime pointer')
        value=json.loads(pointer.read_text())
        storage=Path(value['root'])
        if not storage.is_absolute() or not storage.parent.is_mount() or not (storage/'runs/scored').is_dir():
            raise ValueError('Memory evidence drive unavailable; mount it before the complete workflow audit')
        folders.extend((storage/'runs/scored').glob('*/*/run.json'))
    return sorted(set(folders))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=('begin','audit','status'))
    parser.add_argument('path',nargs='?');args=parser.parse_args()
    if args.command=='begin':print(begin(args.path)[0])
    elif args.command=='audit':print(json.dumps(audit(args.path)))
    else:
        runs=discover_runs()
        print(json.dumps([audit(p.parent) for p in runs],indent=2))


if __name__=='__main__':main()
