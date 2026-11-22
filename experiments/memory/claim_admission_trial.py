"""Bounded source-local admission trial; independent labels applied afterwards."""
from dataclasses import asdict
import json
import signal

from experiments.memory.runtime import ROOT, SSD, require_ssd
from experiments.memory.claim_admission import AdmissionPipeline
from experiments.memory.subject_contract import Claim
from tavi.experiment_workflow import begin, audit


def run():
    require_ssd()
    import httpx
    broker = json.loads((SSD / 'private-config/broker.json').read_text())
    if not broker['paid']:
        raise ValueError('Bounded paid gateway required')
    folder, plan = begin(ROOT / 'experiments/memory/claim-admission-protocol-v1.json',
                         run_root=SSD / 'runs/scored')
    print(json.dumps({'run': str(folder), 'audit': audit(folder)}), flush=True)
    fixture = json.loads((ROOT / plan['configuration']['input']).read_text())
    pipeline = AdmissionPipeline(broker)
    observations = {'sources': [], 'controls': [], 'errors': []}

    def save():
        (folder / 'observations.json').write_text(json.dumps(observations, indent=2))

    def expired(*args):
        raise TimeoutError('Admission trial wall bound reached')

    signal.signal(signal.SIGALRM, expired)
    signal.alarm(plan['limits']['maximum_wall_seconds'])
    try:
        if len(fixture['sources']) != 40 or len(fixture['controls']) != 12:
            raise ValueError('Frozen fixture counts changed')
        for source in fixture['sources']:
            # Save proposals before verification so a failed second call cannot
            # erase the extractor's output or hide a partially processed source.
            claims = pipeline.extract(source, fixture['people'])
            row = {'source_id': source['id'], 'proposals': [asdict(c) for c in claims],
                   'validation': None}
            observations['sources'].append(row)
            save()
            row['validation'] = pipeline.validate(source, fixture['people'], claims)
            save()
            print(json.dumps({'source': source['id'], 'proposed': len(claims),
                              'admitted': len(row['validation']['admissions'])}), flush=True)
        ledger = {s['id']: s for s in fixture['sources']}
        for control in fixture['controls']:
            result = pipeline.validate(ledger[control['source_id']], fixture['people'],
                                       [Claim(**c) for c in control['proposals']])
            observations['controls'].append({'id': control['id'], 'validation': result})
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
