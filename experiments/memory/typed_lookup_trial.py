"""Zero-inference chronological replay of actual automatic admissions."""
from copy import deepcopy
import json
import math
import time

from experiments.memory.runtime import ROOT, SSD, require_ssd
from experiments.memory.source_context import timestamp
from experiments.memory.typed_lookup import MemorySnapshot, source_digest
from tavi.experiment_workflow import begin, finish, audit, digest


def matches(actual, expected):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and matches(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(matches(a, e) for a, e in zip(actual, expected))
    return actual == expected and type(actual) is type(expected)


def references(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'source_id':
                yield item
            elif key == 'source_ids':
                yield from item
            else:
                yield from references(item)
    elif isinstance(value, list):
        for item in value:
            yield from references(item)


def run():
    require_ssd()
    folder, plan = begin(ROOT / 'experiments/memory/typed-lookup-protocol-v1.json',
                         run_root=SSD / 'runs/scored')
    print(json.dumps({'run': str(folder), 'preflight': audit(folder)}), flush=True)
    config = plan['configuration']
    fixture = json.loads((ROOT / config['input']).read_text())
    saved = json.loads(open(config['admissions']).read())
    cases = json.loads((ROOT / config['cases']).read_text())
    # begin verified both input digests against the frozen manifest. Bind each
    # processed row to that exact original canonical source, never a later edit.
    ledger = {s['id']: s for s in fixture['sources']}
    processed = [{**row, 'source_sha256': source_digest(ledger[row['source_id']])}
                 for row in saved['sources']]
    observations, errors = [], []
    started = time.monotonic()
    for case in cases:
        try:
            if time.monotonic() - started > plan['limits']['maximum_wall_seconds']:
                raise TimeoutError('Lookup replay wall bound reached')
            sources, rows = deepcopy(fixture['sources']), deepcopy(processed)
            mutation = case['mutation'] or {}
            for row in rows:
                if row['source_id'] == mutation.get('pending_source'):
                    row['validation'] = None
            for source in sources:
                if source['id'] == mutation.get('alter_source'):
                    source['text'] += ' This source changed after its validation.'
            before = time.perf_counter()
            snapshot = MemorySnapshot(fixture['people'], sources, rows,
                                      deleted_source_ids=case['deleted_source_ids'])
            result = snapshot.lookup(case['request'], audience=case['audience'], as_of=case['as_of'])
            observations.append({'case': case['id'], 'result': result,
                                 'snapshot_and_lookup_ms': (time.perf_counter() - before) * 1000})
        except Exception as exc:
            errors.append({'case': case['id'], 'error': type(exc).__name__ + ': ' + str(exc)})
    # Evaluation oracle never enters lookup construction or execution.
    oracle = json.loads((ROOT / config['oracle']).read_text())
    checked = [{**row, 'policy_match': matches(row['result'], oracle['policy_outputs'][row['case']])}
               for row in observations]
    lookup = {r['case']: r['result'] for r in observations}
    unauthorized = 0
    for case in cases:
        for sid in references(lookup.get(case['id'], {})):
            if (sid not in ledger or sid in case['deleted_source_ids']
                    or not set(case['audience']) <= set(ledger[sid]['audience_ids'])
                    or timestamp(ledger[sid]['at']) > timestamp(case['as_of'])):
                unauthorized += 1
    costs = sorted(r['snapshot_and_lookup_ms'] for r in observations)
    metrics = {'cases_processed': len(observations), 'policy_cases_correct': sum(r['policy_match'] for r in checked),
               'unauthorized_source_references': unauthorized,
               'private_value_leaks': sum('Azul' in json.dumps(lookup.get(q, {})) for q in ['q20', 'q21']),
               'collection_errors': len(errors), 'additional_api_usd': 0,
               'snapshot_and_lookup_p95_ms': costs[math.ceil(len(costs) * .95)-1] if costs else None,
               'original_source_warranted_patterns_recalled': sum(any(
                   p['status'] == 'tentative' for p in lookup.get(q, {}).get('patterns', []))
                   for q in oracle['pipeline_learning_coverage']),
               'original_source_warranted_patterns': len(oracle['pipeline_learning_coverage'])}
    review = {'metrics': metrics, 'run': str(folder), 'critical_review': [
        'Policy criteria concern safe reduction of admitted evidence, not extraction completeness or original E5 learning acceptance.',
        'One post-resumption pattern is missed because the upstream admission rejected n025. A policy pass cannot turn this missing learning into accepted recall.',
        'Same-session repeats, withdrawal, new explicit uncertainty, private scope, tombstones, pending writes and changed source bindings are included.',
        'Target subject and operation are supplied as typed inputs here. Natural-language target selection and free-text response adherence remain unqualified.',
        'Timing is in-process snapshot plus lookup on40 fictional sources; not native engine latency, steady-state large-memory performance or audible voice timing.',
        'No physical persistence, power-loss, real household identity or human experience qualification.'],
        'source_bindings': {config['input']: digest(ROOT/config['input']), config['admissions']: digest(config['admissions'])}}
    (folder / 'observations.json').write_text(json.dumps({'queries': checked, 'errors': errors}, indent=2))
    (folder / 'critical-review.json').write_text(json.dumps(review, indent=2))
    result = finish(folder, metrics, artifacts=[folder/'observations.json', folder/'critical-review.json'],
                    completed=not errors, error=json.dumps(errors) if errors else None)
    review.update(outcome=result['decision']['outcome'], audit=audit(folder))
    (ROOT/'docs/evaluations/paprika_memory_typed_lookup_01.json').write_text(json.dumps(review, indent=2))
    print(json.dumps(review, indent=2))


if __name__ == '__main__':
    run()
