"""Bounded development answer replay: same retrieval/model, new source envelope.

No native re-ingestion or profile repair; quality labels are reviewed separately.
"""
import argparse
import json
import os
import signal
import time

from experiments.memory.runtime import ROOT, SSD, require_ssd
from experiments.memory.pilot import answer
from experiments.memory.source_context import pack_sources
from tavi.experiment_workflow import begin, audit


def run(protocols):
    require_ssd()
    os.environ['TIKTOKEN_CACHE_DIR'] = str(SSD / 'models/tiktoken')
    import httpx
    import tiktoken
    encoding = tiktoken.get_encoding('o200k_base')
    broker = json.loads((SSD / 'private-config/broker.json').read_text())
    if not broker['paid']:
        raise ValueError('Prospectively bounded paid broker required')
    runs = []
    for protocol in protocols:
        folder, plan = begin(protocol, run_root=SSD / 'runs/scored')
        print(json.dumps({'run': str(folder), 'audit': audit(folder)}), flush=True)
        runs.append((folder, plan, {'queries': [], 'errors': [], 'development_reuse': True}))

    def expired(*args):
        raise TimeoutError('Frozen source-answer replay wall bound reached')

    signal.signal(signal.SIGALRM, expired)
    signal.alarm(min(p['limits']['maximum_wall_seconds'] for _, p, _ in runs))
    try:
        for folder, plan, observations in runs:
            try:
                engine = plan['configuration']['engine']
                inputs = json.loads(open(plan['configuration']['saved_retrievals']).read())
                corpus = json.loads((ROOT / plan['configuration']['corpus']).read_text())
                if len(inputs[engine]) != 80:
                    raise ValueError('Exactly80 frozen retrievals required')
                for saved in inputs[engine]:
                    q = saved['question']
                    stop = next(i for i, e in enumerate(corpus['episodes']) if e['id'] == q['after'])
                    started = time.monotonic()
                    envelope = pack_sources(engine, saved['retrieval']['native_context'],
                                            corpus['episodes'][:stop + 1], q['audience_ids'],
                                            encoding, as_of=q['at'], deleted_source_ids=[])
                    pack_ms = (time.monotonic() - started) * 1000
                    public_question = {k: q[k] for k in ('id', 'text', 'asker', 'audience_ids', 'at')}
                    response = answer(engine, public_question, corpus['people'], envelope['context'], broker)
                    observations['queries'].append({'question': q, 'envelope': envelope,
                        'pack_only_ms': pack_ms, 'answer': response,
                        'review_status': 'pending_explicit_source_review'})
                    (folder / 'observations.json').write_text(json.dumps(observations, indent=2))
                    if len(observations['queries']) % 10 == 0:
                        print(json.dumps({'engine': engine, 'answers': len(observations['queries'])}), flush=True)
            except Exception as exc:
                observations['errors'].append(type(exc).__name__ + ': ' + str(exc))
                (folder / 'observations.json').write_text(json.dumps(observations, indent=2))
                if isinstance(exc, TimeoutError):
                    break
    finally:
        signal.alarm(0)
        response = httpx.post(broker['base_url'] + '/control/disable-paid',
                              headers={'Authorization': 'Bearer ' + broker['token']}, timeout=100)
        response.raise_for_status()
        calls = response.json()['calls']
        for folder, plan, observations in runs:
            engine = plan['configuration']['engine']
            (folder / 'calls-final.json').write_text(json.dumps([c for c in calls if c['engine'] == engine], indent=2))
            (folder / 'observations.json').write_text(json.dumps(observations, indent=2))
    print(json.dumps({'awaiting': 'Explicit labels and original prospective replay criteria; no engine acceptance',
                      'runs': [str(f) for f, _, _ in runs]}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('protocols', nargs=2)
    run(parser.parse_args().protocols)
