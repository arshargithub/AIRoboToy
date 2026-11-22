"""One bounded paired attribution diagnostic; oracle never enters inference."""
import json
import os
import signal

from experiments.memory.runtime import ROOT, SSD, require_ssd
from experiments.memory.pilot import answer
from experiments.memory.source_context import pack_sources
from experiments.memory.source_context_attributed import pack_attributed
from tavi.experiment_workflow import begin, audit


def run():
    require_ssd()
    os.environ['TIKTOKEN_CACHE_DIR'] = str(SSD / 'models/tiktoken')
    import httpx
    import tiktoken
    encoding = tiktoken.get_encoding('o200k_base')
    broker = json.loads((SSD / 'private-config/broker.json').read_text())
    if not broker['paid']:
        raise ValueError('Bounded paid broker required')
    folder, plan = begin(ROOT / 'experiments/memory/attribution-protocol-v1.json',
                         run_root=SSD / 'runs/scored')
    print(json.dumps({'run': str(folder), 'audit': audit(folder)}), flush=True)
    corpus = json.loads((ROOT / plan['configuration']['cases']).read_text())
    observations = {'queries': [], 'errors': []}

    def save():
        (folder / 'observations.json').write_text(json.dumps(observations, indent=2))

    def expired(*args):
        raise TimeoutError('Frozen attribution diagnostic wall bound reached')

    signal.signal(signal.SIGALRM, expired)
    signal.alarm(plan['limits']['maximum_wall_seconds'])
    try:
        if len(corpus['cases']) != 20:
            raise ValueError('Exactly20 frozen cases required')
        for index, case in enumerate(corpus['cases']):
            variants = ['raw_header_control', 'inline_attribution']
            if index % 2:
                variants.reverse()
            for variant in variants:
                q = case['question']
                kwargs = dict(as_of=q['at'], deleted_source_ids=case['deleted_source_ids'])
                packer = pack_sources
                if variant == 'inline_attribution':
                    packer = pack_attributed
                    kwargs['people'] = corpus['people']
                envelope = packer('sqlite', [{'episode': e} for e in case['episodes']],
                                  case['episodes'], q['audience_ids'], encoding, **kwargs)
                response = answer('sqlite', q, corpus['people'], envelope['context'], broker)
                observations['queries'].append({'case': case['id'], 'variant': variant,
                                                'envelope': envelope, 'answer': response})
                save()
            print(json.dumps({'case': case['id'], 'answers': len(observations['queries'])}), flush=True)
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
    print(json.dumps({'awaiting_explicit_review': str(folder)}), flush=True)


if __name__ == '__main__':
    run()
