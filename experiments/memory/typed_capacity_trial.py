"""Bounded fictional typed-query/answer trial; no oracle in inference."""
import json
import os
import signal
import argparse
import time
import secrets

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

    dialogues = {model: StrictTypedDialogue(broker, tiktoken.get_encoding('o200k_base'), trace,
                                            model=model) for model in config['models']}

    def expired(*args):
        raise TimeoutError('Typed dialogue wall bound reached')

    signal.signal(signal.SIGALRM, expired)
    signal.alarm(plan['limits']['maximum_wall_seconds'])
    try:
        if len(cases) != 26:
            raise ValueError('Frozen case count changed')
        review = []; mapping = {}
        for index, case in enumerate(cases):
            models = config['models'][::1 if index % 2 == 0 else -1]
            candidates = []
            for model in models:
                started = time.monotonic()
                result = dialogues[model].respond(case['question'], case['speaker'], snapshot,
                                                  audience=case['audience'], as_of=case['as_of'])
                observations['cases'].append({'id': case['id'], 'model': model, 'result': result,
                                             'elapsed_ms': (time.monotonic()-started)*1000})
                candidates.append((model, result)); save()
            secrets.SystemRandom().shuffle(candidates)
            for slot, (model, result) in enumerate(candidates):
                key = case['id'] + '-' + str(slot+1)
                mapping[key] = model
                review.append({'key': key, 'question': case['question'], 'result': result})
            (folder/'blind-review.json').write_text(json.dumps(review, indent=2))
            (folder/'blind-key.json').write_text(json.dumps(mapping, indent=2))
            print(json.dumps({'case': case['id'], 'paired_complete': True}), flush=True)
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
