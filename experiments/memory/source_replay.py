"""Zero-inference packing replay on already collected native retrievals.

Source-link coverage is a retrieval/packing diagnostic, never an answer-quality
score. Evaluation oracles are used only after the candidate context is built.
"""
import argparse
import json
import os
from pathlib import Path
import time

from experiments.memory.runtime import ROOT, SSD, require_ssd
from experiments.memory.source_context import pack_sources
from tavi.experiment_workflow import begin, audit, finish


def run(protocol):
    require_ssd()
    os.environ['TIKTOKEN_CACHE_DIR'] = str(SSD / 'models/tiktoken')
    import tiktoken
    encoding = tiktoken.get_encoding('o200k_base')
    folder, plan = begin(protocol, run_root=SSD / 'runs/scored')
    print(json.dumps({'run': str(folder), 'audit': audit(folder)}), flush=True)
    inputs = json.loads(Path(plan['configuration']['saved_retrievals']).read_text())
    corpus = json.loads((ROOT / plan['configuration']['corpus']).read_text())
    rows, errors = [], []
    deadline = time.monotonic() + plan['limits']['maximum_wall_seconds']
    try:
        for engine, queries in inputs.items():
            for query in queries:
                if time.monotonic() > deadline:
                    raise TimeoutError('Frozen replay wall bound reached')
                q = query['question']
                stop = next(i for i, e in enumerate(corpus['episodes']) if e['id'] == q['after'])
                active = corpus['episodes'][:stop + 1]
                started = time.monotonic()
                candidate = pack_sources(engine, query['retrieval']['native_context'], active,
                                         q['audience_ids'], encoding, as_of=q['at'],
                                         deleted_source_ids=[])
                elapsed = (time.monotonic() - started) * 1000
                # Held-separate labels never enter source selection or packing.
                expected = set(corpus['oracle'][q['id']].get('source_ids', []))
                original_ids = set(json.loads(query['envelope']['context'])['source_headers'])
                candidate_ids = set(candidate['selected_source_ids'])
                rows.append({'engine': engine, 'question_id': q['id'],
                             'expected_sources': sorted(expected),
                             'original_source_links': sorted(original_ids & expected),
                             'candidate_source_links': sorted(candidate_ids & expected),
                             'pack_only_ms': elapsed, 'candidate': candidate})
    except Exception as exc:
        errors.append(type(exc).__name__ + ': ' + str(exc))
    result = {'rows': rows, 'errors': errors, 'additional_api_usd': 0,
              'answer_quality_scored': False,
              'limitation': 'Same reused retrievals; no new ingestion, inference, native profiles or end-to-end timing.'}
    (folder / 'observations.json').write_text(json.dumps(result, indent=2))
    metrics = {'contexts_replayed': len(rows), 'errors': len(errors),
               'context_budget_violations': sum(r['candidate']['tokens'] > 1500 for r in rows),
               'additional_api_usd': 0}
    for engine in inputs:
        selected = [r for r in rows if r['engine'] == engine]
        with_sources = [r for r in selected if r['expected_sources']]
        metrics[engine] = {
            'contexts': len(selected),
            'questions_with_expected_sources': len(with_sources),
            'all_expected_source_links_original': sum(set(r['expected_sources']) <= set(r['original_source_links']) for r in with_sources),
            'all_expected_source_links_candidate': sum(set(r['expected_sources']) <= set(r['candidate_source_links']) for r in with_sources),
            'lost_expected_links': sum(len(set(r['original_source_links']) - set(r['candidate_source_links'])) for r in selected),
            'gained_expected_links': sum(len(set(r['candidate_source_links']) - set(r['original_source_links'])) for r in selected),
        }
    (folder / 'critical-review.json').write_text(json.dumps({
        'metrics': metrics,
        'review': ['A real source ID may support a false native assertion. Link coverage does not certify entailment.',
                   'Canonical quotations remove generated assertion prose, but an answer model may still misread them.',
                   'No factual accuracy or engine acceptance follows from packing completeness.',
                   'Performance is packing only; native retrieval, inference, speech and startup are excluded.',
                   'Deletion/time/audience adversarial cases have separate unit coverage; these saved queries precede the full-run deletion.']}, indent=2))
    outcome = finish(folder, metrics, artifacts=[folder / 'observations.json', folder / 'critical-review.json'],
                     completed=not errors, error='; '.join(errors) if errors else None)
    print(json.dumps({'run': str(folder), 'metrics': metrics,
                      'decision': outcome['decision']['outcome'], 'audit': audit(folder)}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('protocol')
    run(parser.parse_args().protocol)
