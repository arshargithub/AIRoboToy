"""Prepare a source-paired review with per-question shuffled engine identities.

No inference, scoring or answer changes. The mapping is retained separately and
must not be revealed until explicit labels are saved. Blinding reduces a ranking
bias; writing the harness and recognizing prose styles still limit independence.
"""
import argparse
import hashlib
import json
from pathlib import Path
import random
import re
import secrets

from tavi.experiment_workflow import digest


def query_digest(rows):
    return hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def prepare(folders,destination,allow_pending_operations=False):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=False)
    all_runs=[];questions={};corpus=None
    for folder in map(Path,folders):
        if not (folder/'calls-final.json').exists() and not allow_pending_operations:
            raise ValueError('Collection has not stopped or spending has not been sealed')
        plan=json.loads((folder/'protocol.json').read_text());record=json.loads((folder/'run.json').read_text())
        corpus_path=Path(__file__).resolve().parents[2]/plan['configuration']['corpus']
        if digest(corpus_path)!=record['input_sha256'][plan['configuration']['corpus']]:raise ValueError('Corpus changed')
        candidate=json.loads(corpus_path.read_text())
        if corpus is not None and candidate!=corpus:raise ValueError('Review requires matched corpora')
        corpus=candidate;data=json.loads((folder/'observations.json').read_text())
        if allow_pending_operations and len({q['question']['id'] for q in data['queries']})!=80:
            raise ValueError('All80 answers must be collected before review overlaps maintenance')
        all_runs.append({'folder':str(folder),'queries_sha256':query_digest(data['queries']),
                         'operations_pending':not (folder/'calls-final.json').exists(),
                         'engine':plan['configuration']['engine']})
        for row in data['queries']:questions.setdefault(row['question']['id'],[]).append((str(folder),plan['configuration']['engine'],row))
    seed=secrets.token_hex(32);rng=random.Random(seed);bundle=[];mapping={}
    source={e['id']:e for e in corpus['episodes']}
    for qid,rows in sorted(questions.items()):
        rng.shuffle(rows);entries=[];ids=set();oracle=corpus['oracle'][qid]
        for field in ('source_ids','hidden_source_ids','superseded_ids'):ids.update(oracle.get(field,[]))
        for i,(folder,engine,row) in enumerate(rows):
            blind=qid+'-'+chr(ord('A')+i);context=json.loads(row['envelope']['context']);ids.update(context['source_headers'])
            ids.update(re.findall(r'\be\d{3}\b',row['answer']['text']))
            entries.append({'blind_id':blind,'answer':row['answer']['text'],
                'visible_facts':[{'text':f['text'],'sources':f['sources']} for f in context['facts']],
                'visible_source_ids':list(context['source_headers'])})
            mapping[blind]={'folder':folder,'engine':engine,'question_id':qid,'answer_sha256':hashlib.sha256(row['answer']['text'].encode()).hexdigest()}
        bundle.append({'question':rows[0][2]['question'],'oracle':oracle,'source_evidence':[source[s] for s in sorted(ids) if s in source], 'answers':entries})
    (destination/'review-bundle.json').write_text(json.dumps(bundle,indent=2))
    (destination/'private-reveal-map.json').write_text(json.dumps({'seed':seed,'runs':all_runs,'mapping':mapping},indent=2));(destination/'private-reveal-map.json').chmod(0o600)
    print(json.dumps({'review_bundle':str(destination/'review-bundle.json'),'questions':len(bundle),'answers':len(mapping),'mapping_hidden':True}))


def reveal(destination):
    destination=Path(destination);labels=json.loads((destination/'labels.json').read_text())
    mapping=json.loads((destination/'private-reveal-map.json').read_text())
    if set(labels)!=set(mapping['mapping']):raise ValueError('Every collected answer must be explicitly reviewed before revealing engine labels')
    for label in labels.values():
        if not isinstance(label.get('rationale'),str) or not label['rationale'].strip():raise ValueError('Explicit review rationale required')
        for k in ('task_correct','all_claims_grounded','privacy_violation','identity_error','unsupported_strong_pattern_claim','warranted_pattern_recalled'):
            if type(label.get(k)) is not bool:raise ValueError('Missing explicit review field '+k)
    grouped={}
    for blind,info in mapping['mapping'].items():
        grouped.setdefault(info['folder'],{})[info['question_id']]={**labels[blind],'blind_id':blind}
    for info in mapping['runs']:
        folder=Path(info['folder'])
        if query_digest(json.loads((folder/'observations.json').read_text())['queries'])!=info['queries_sha256']:
            raise ValueError('Collected question/answer/context evidence changed during review')
        target=folder/'reviewed-labels.json'
        if target.exists():raise ValueError('Refusing to overwrite saved review')
        target.write_text(json.dumps(grouped[info['folder']],indent=2))
    print(json.dumps({'reviewed_answers':len(labels),'runs':mapping['runs']},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','reveal']);p.add_argument('destination');p.add_argument('folders',nargs='*');p.add_argument('--allow-pending-operations',action='store_true');a=p.parse_args()
    if a.mode=='prepare':prepare(a.folders,a.destination,a.allow_pending_operations)
    else:reveal(a.destination)
