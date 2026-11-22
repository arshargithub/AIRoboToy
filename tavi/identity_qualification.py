"""One prospectively bound evaluation of frozen-cutoff, reviewed held-out data.

Only the individual identity component can qualify here. Group engagement and
the broader household/E5/E6 gates are explicitly not accepted by this module.
"""
import importlib.util
import json
from pathlib import Path
from uuid import uuid4
from tavi.experiment_workflow import ROOT,begin,audit,finish,digest,discover_runs
from tavi.identity_policy import rank
from tavi.identity_catalog import PEOPLE
from tavi.speaker_profile import write_json
from experiments.memory.runtime import SSD


def qualify(calibration):
    calibration.catalog.refresh()
    root=calibration.root;candidate_path=root/'development-policy.json';pointer=root/'qualification-result.json'
    if pointer.exists():
        result=json.loads(pointer.read_text())
        if result.get('profiles_revision')!=calibration.catalog.revision or result.get('model_sha256')!=calibration.model:
            return {'status':'qualification_inputs_changed','recognition_enabled':False}
        return result
    if not candidate_path.exists():return {'status':'development_needed','recognition_enabled':False}
    candidate=json.loads(candidate_path.read_text());catalog=calibration.catalog;catalog.refresh()
    if candidate.get('profiles_revision')!=catalog.revision or candidate.get('model_sha256')!=calibration.model or candidate.get('decision_code_sha256')!=digest(ROOT/'tavi/identity_policy.py'):
        return {'status':'development_policy_changed','recognition_enabled':False}
    rows=calibration.corpus('heldout')
    counts={p:sum(r['label_kind']=='known' and r['person_id']==p and r['eligible'] for r in rows) for p in PEOPLE}
    unknown=sum(r['label_kind']=='unknown' for r in rows);short=sum(r['label_kind']=='short' for r in rows);overlap=sum(r['label_kind']=='overlap' for r in rows)
    if set(catalog.entries)!=set(PEOPLE) or min(counts.values())<25 or unknown<20 or short+overlap<20 or not short or not overlap:
        return {'status':'heldout_evidence_needed','known_eligible':counts,'unknown':unknown,'short':short,'overlap':overlap,'recognition_enabled':False}
    # All held-out input rows and exact cutoffs are bound BEFORE applying decisions.
    directory=root/'evaluation-inputs'/uuid4().hex;directory.mkdir(parents=True,mode=0o700)
    rows_path=directory/'rows.json';write_json(rows_path,rows)
    manifest=directory/'manifest.json'
    write_json(manifest,{'files':[{'path':str(rows_path),'sha256':digest(rows_path)},
        {'path':str(candidate_path),'sha256':digest(candidate_path)}]+[{'path':str(e['path']),'sha256':digest(e['path'])} for e in catalog.entries.values()]})
    template=json.loads((ROOT/'experiments/speaker-id/identity-heldout-protocol-v1.json').read_text())
    template['inputs']=[str(manifest),str(rows_path),str(candidate_path),'experiments/speaker-id/model-manifest.json'];template['input_manifests']=[str(manifest)]
    protocol=directory/'protocol.json';write_json(protocol,template)
    # Complete the checker before beginning the single scored run.
    for run in discover_runs():audit(run.parent)
    folder,_=begin(protocol,run_root=SSD/'runs/scored');audit(folder)
    # Durable once-only marker precedes scoring, including crash/error recovery.
    write_json(pointer,{'status':'identity_evaluation_interrupted','run':str(folder),'recognition_enabled':False,
        'profiles_revision':catalog.revision,'model_sha256':calibration.model})
    try:
        spec=importlib.util.spec_from_file_location('paprika_heldout_accounting',ROOT/'experiments/speaker-id/identity_metrics.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        decided=[{**r,'decision':rank(r['scores'],candidate['threshold'],candidate['margin'],eligible=r['eligible'])} for r in rows]
        for r in decided:r['memory_authorized']=r['decision']!='unknown' # hypothetical permission if this rule were activated
        report=module.evaluate(decided,model_sha256=calibration.model,enrollment=catalog.enrollment(),development_sessions=candidate['development_sessions']+catalog.excluded_sessions())
        metric={'identity_component_pass':report['identity_subscreen']=='pass','heldout_independent':True,'additional_api_usd':0,'real_cloud_requests':0}
        write_json(folder/'accounting.json',report)
        sealed=finish(folder,metric,artifacts=[folder/'accounting.json',rows_path,candidate_path],completed=True)
    except Exception as error:
        finish(folder,{},artifacts=[rows_path,candidate_path],completed=False,error=type(error).__name__)
        result={'status':'identity_component_error','run':str(folder),'recognition_enabled':False,
            'profiles_revision':catalog.revision,'model_sha256':calibration.model}
        write_json(pointer,result);return result
    result={'status':'individual_identity_component_qualified' if metric['identity_component_pass'] else 'identity_component_failed',
        'run':str(folder),'profiles_revision':catalog.revision,'model_sha256':calibration.model,'E4_accepted':False,'remaining':['group follow-ups, side conversations and session closure','household memory and acoustic/product acceptance'],
        'recognition_enabled':metric['identity_component_pass']}
    if metric['identity_component_pass']:
        certificate={'issuer':'paprika_identity_component_v1','run':str(folder),'rows_path':str(rows_path),'development_policy_path':str(candidate_path),
            'profiles_revision':catalog.revision,'model_sha256':calibration.model,
            **{k:candidate[k] for k in ('threshold','margin','development_sessions','development_pcm_sha256')}}
        write_json(root.parent/'identity-policy.json',certificate)
    write_json(pointer,result);return result
