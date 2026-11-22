"""Frozen-proposal replay plus fresh temporal controls; no oracle in inference."""
import json
import signal

from experiments.memory.runtime import ROOT, SSD, require_ssd
from experiments.memory.claim_admission_temporal import TemporalAdmissionPipeline
from experiments.memory.subject_contract import Claim
from tavi.experiment_workflow import begin, audit


def run():
    require_ssd()
    import httpx
    broker = json.loads((SSD / 'private-config/broker.json').read_text())
    if not broker['paid']:
        raise ValueError('Bounded paid gateway required')
    folder, plan = begin(ROOT / 'experiments/memory/claim-temporal-protocol-v1.json',
                         run_root=SSD / 'runs/scored')
    print(json.dumps({'run': str(folder), 'audit': audit(folder)}), flush=True)
    fixture = json.loads((ROOT / plan['configuration']['input']).read_text())
    saved = json.loads(open(plan['configuration']['saved_proposals']).read())
    fresh = json.loads((ROOT / plan['configuration']['temporal_controls']).read_text())
    pipeline = TemporalAdmissionPipeline(broker)
    observations = {'sources': [], 'controls': [], 'fresh_controls': [], 'errors': []}

    def save():
        (folder / 'observations.json').write_text(json.dumps(observations, indent=2))

    def expired(*args):
        raise TimeoutError('Temporal admission trial wall bound reached')

    signal.signal(signal.SIGALRM, expired)
    signal.alarm(plan['limits']['maximum_wall_seconds'])
    try:
        ledger = {s['id']: s for s in fixture['sources']}
        if len(saved['sources']) != 40 or len(fresh['controls']) != 12:
            raise ValueError('Frozen source/control counts changed')
        for row in saved['sources']:
            proposals = [Claim(**c) for c in row['proposals']]
            result = pipeline.validate(ledger[row['source_id']], fixture['people'], proposals)
            observations['sources'].append({'source_id': row['source_id'],
                                             'proposals': row['proposals'], 'validation': result})
            save()
            print(json.dumps({'source': row['source_id'], 'admitted': len(result['admissions'])}), flush=True)
        for control in fixture['controls']:
            result = pipeline.validate(ledger[control['source_id']], fixture['people'],
                                       [Claim(**c) for c in control['proposals']])
            observations['controls'].append({'id': control['id'], 'validation': result})
            save()
        for control in fresh['controls']:
            result = pipeline.validate(control['source'], fresh['people'],
                                       [Claim(**c) for c in control['proposals']])
            observations['fresh_controls'].append({'id': control['id'], 'validation': result})
            save()
    except Exception as exc:
        observations['errors'].append(type(exc).__name__ + ': ' + str(exc))
        save()
    finally:
        signal.alarm(0)
        response = httpx.post(broker['base_url'] + '/control/disable-paid',
                              headers={'Authorization': 'Bearer ' + broker['token']}, timeout=100)
        response.raise_for_status()
        (folder / 'calls-final.json').write_text(json.dumps(response.json()['calls'], indent=2))
        save()
    print(json.dumps({'awaiting_explicit_source_review': str(folder)}), flush=True)


if __name__ == '__main__':
    run()
