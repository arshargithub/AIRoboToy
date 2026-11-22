"""Prospectively bind and seal each explicit short local calibration visit."""
import json
from pathlib import Path
from experiments.memory.runtime import ROOT,SSD
from tavi.experiment_workflow import begin,audit,finish


def bind_visit(body):
    person=body['person_id'];child=person in ('childtwo','childone','overlap')
    consent={'adult':True,'recording':True,'cloud':False,'processing':'local-only','subject_id':person,
        'subject_willing':True,'alone':person!='overlap','two_speakers_agree':person=='overlap','retain_audio':body['retain_audio'],'supervised':child,'own_voice':not child,
        'phase':body['phase'],'outside_family':person=='guest','different_occasion':body.get('different_occasion') is True}
    folder,_=begin(ROOT/'experiments/speaker-id/calibration-capture-protocol-v1.json',run_root=SSD/'runs/scored',consent=consent)
    audit(folder);return folder


def seal_visit(folder,visit):
    if not visit.get('workflow_run'):return
    run=Path(visit['workflow_run']);record=json.loads((run/'run.json').read_text())
    if record['state']=='finished':audit(run);return
    metrics={'subject_bound':True,'reviewed':all(a['review'] in ('keep','exclude') for a in visit['attempts'] if a['outcome'] in ('clear','short_control')),
        'attempts':len(visit['attempts']),'kept':sum(a['review']=='keep' for a in visit['attempts']),
        'candidate_authority_disabled':True,'cloud_requests':0,'additional_api_usd':0}
    artifacts=[folder/'visit.json']+[folder/a['reference_file'] for a in visit['attempts'] if a.get('reference_file')]
    finish(run,metrics,artifacts=artifacts,completed=True)
