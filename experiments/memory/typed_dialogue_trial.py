"""Bounded fictional typed-query/answer trial; no oracle in inference."""
import json
import os
import signal
import argparse

from experiments.memory.runtime import ROOT, SSD, require_ssd
from experiments.memory.typed_lookup import MemorySnapshot, source_digest
from experiments.memory.typed_dialogue import TypedDialogue
from experiments.memory.typed_dialogue_strict import StrictTypedDialogue
from tavi.experiment_workflow import begin, audit


def run(protocol):
    require_ssd()
    os.environ['TIKTOKEN_CACHE_DIR'] = str(SSD / 'models/tiktoken')
    import httpx
    import tiktoken
    broker = json.loads((SSD/'private-config/broker.json').read_text())
    if not broker['paid']:
        raise ValueError('Bounded paid broker required')
    folder, plan = begin(ROOT/protocol,
                         run_root=SSD/'runs/scored')
    print(json.dumps({'run': str(folder), 'audit': audit(folder)}), flush=True)
    config = plan['configuration']
    fixture = json.loads((ROOT/config['input']).read_text())
    saved = json.loads(open(config['admissions']).read())
    cases = json.loads((ROOT/config['cases']).read_text())
    ledger = {s['id']: s for s in fixture['sources']}
    rows = [{**row, 'source_sha256': source_digest(ledger[row['source_id']])} for row in saved['sources']]
    snapshot = MemorySnapshot(fixture['people'], fixture['sources'], rows)
    observations = {'cases': [], 'errors': [], 'model_trace': []}

    def save():
        (folder/'observations.json').write_text(json.dumps(observations, indent=2))

    def trace(value):
        observations['model_trace'].append(value)
        save()

    dialogue = (StrictTypedDialogue(broker, tiktoken.get_encoding('o200k_base'), trace)
                if config.get('strict_output_schemas') else
                TypedDialogue(broker, tiktoken.get_encoding('o200k_base')))

    def expired(*args):
        raise TimeoutError('Typed dialogue wall bound reached')

    signal.signal(signal.SIGALRM, expired)
    signal.alarm(plan['limits']['maximum_wall_seconds'])
    try:
        if len(cases) != 26:
            raise ValueError('Frozen case count changed')
        for case in cases:
            result = dialogue.respond(case['question'], case['speaker'], snapshot,
                                      audience=case['audience'], as_of=case['as_of'])
            observations['cases'].append({'id': case['id'], 'result': result})
            save()
            print(json.dumps({'case': case['id'], 'route': result['route']['status']}), flush=True)
    except Exception as exc:
        observations['errors'].append(type(exc).__name__ + ': ' + str(exc))
        save()
    finally:
        signal.alarm(0)
        response = httpx.post(broker['base_url'] + '/control/disable-paid',
                              headers={'Authorization': 'Bearer ' + broker['token']}, timeout=100)
        response.raise_for_status()
        (folder/'calls-final.json').write_text(json.dumps(response.json()['calls'], indent=2))
        save()
    print(json.dumps({'awaiting_explicit_review': str(folder)}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('protocol')
    run(parser.parse_args().protocol)
