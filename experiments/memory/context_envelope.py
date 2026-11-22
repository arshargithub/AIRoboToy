"""Provenance-preserving experimental context packing, independent of engine.

This adds trusted source metadata, never missing raw utterances or oracle
answers. Native assertions remain untrusted. Source IDs do not prove an engine's
assertion follows from its source, and incomplete lineage is explicitly marked.
"""
import json
import re


def native_facts(engine,native):
    for block in native:
        if engine=='hindsight':
            source_facts=block.get('source_facts') or {}
            for item in block.get('results',[]):
                sources=[]
                candidates=[item]+[source_facts[s] for s in (item.get('source_fact_ids') or []) if s in source_facts]
                for candidate in candidates:
                    if candidate.get('document_id'):sources.append(candidate['document_id'])
                    if (candidate.get('metadata') or {}).get('source_id'):sources.append(candidate['metadata']['source_id'])
                    sources.extend(t.split(':',1)[1] for t in (candidate.get('tags') or []) if t.startswith('source:'))
                yield {'text':item['text'],'sources':sorted(set(sources)),
                    'native_refs':[item['id']], 'kind':item.get('type'),
                    'unresolved_support':[s for s in (item.get('source_fact_ids') or []) if s not in source_facts],
                    'at':item.get('mentioned_at'),'lineage':'native_support_ids_not_entailment_verified'}
        elif engine=='mem0':
            for item in block.get('results',[]):
                source=(item.get('metadata') or {}).get('source_id')
                yield {'text':item['memory'],'sources':[source] if source else [],
                    'native_refs':[item['id']], 'kind':'memory',
                    'at':(item.get('metadata') or {}).get('event_at'),
                    'lineage':'latest_metadata_only; earlier_update_support_may_be_missing'}
        elif engine=='graphiti':
            yield {'text':block['fact'],'sources':block.get('source_ids',[]),
                'native_refs':block.get('episodes',[]),'kind':'temporal_edge',
                'unresolved_support':block.get('unresolved_native_sources',[]),
                'at':block.get('valid_at'),'invalid_at':block.get('invalid_at'),
                'expired_at':block.get('expired_at'),'lineage':'native_episode_support_not_entailment_verified'}
        elif engine=='sqlite':
            if 'fact' in block:
                yield {'text':block['fact']['text'],'sources':block['source_ids'],
                    'native_refs':[block['id']],'kind':block['fact']['kind'],
                    'at':block['at'],'lineage':'single_source_structured_projection'}
                continue
            item=block['episode']
            yield {'text':item['text'],'sources':[item['id']],'native_refs':[item['id']],
                'kind':'verbatim_utterance','at':item['at'],'lineage':'single_verbatim_source'}
        else:raise ValueError('Unknown engine')


def pack(engine,native,episodes,audience,encoding,maximum_tokens=1500):
    if not audience:raise ValueError('An explicit nonempty audience is required')
    if not 1<=maximum_tokens<=1500:raise ValueError('Invalid memory context budget')
    ledger={e['id']:e for e in episodes}
    groups={};rejected=[];trace={}
    for item in native_facts(engine,native):
        ids=item['sources']
        # Unknown or partially hidden support cannot be made visible by deleting
        # an inconvenient source from a multi-source assertion.
        if item.get('unresolved_support') or not ids or any(s not in ledger for s in ids):
            rejected.append({'refs':item['native_refs'],'reason':'unbound_source'});continue
        if any(not set(audience)<=set(ledger[s]['audience_ids']) for s in ids):
            rejected.append({'refs':item['native_refs'],'reason':'audience_not_allowed'});continue
        allowed=set.intersection(*(set(ledger[s]['audience_ids']) for s in ids))
        scope=tuple(sorted(allowed))
        key=re.sub(r'\s+',' ',item['text'].split(' | Involving:',1)[0]).strip().lower()
        existing=groups.setdefault(scope,{})
        if key in existing:
            existing[key]['sources']=sorted(set(existing[key]['sources'])|set(ids))
            existing[key]['native_refs'].extend(item['native_refs'])
        else:existing[key]=dict(item)

    def envelope(items):
        ids=sorted({sid for i in items for sid in i['sources']})
        # These headers come from the canonical ledger, not from the memory
        # model or current question. No raw-source-text fallback is included.
        headers={sid:{'speaker_id':ledger[sid]['speaker_id'],'session_id':ledger[sid]['session'],
                      'at':ledger[sid]['at']} for sid in ids}
        facts=[{k:v for k,v in item.items() if k not in ('native_refs',)} for item in items]
        return {'source_headers':headers,'facts':facts}

    # Round robin across eligible scopes prevents a verbose shared namespace
    # from exhausting the entire budget before a private namespace is visited.
    queues=[list(group.values()) for _,group in sorted(groups.items())]
    chosen=[];omitted=0
    for index in range(max((len(q) for q in queues),default=0)):
        for queue in queues:
            if index>=len(queue):continue
            item=queue[index]
            proposed=json.dumps(envelope(chosen+[item]),ensure_ascii=False,separators=(',',':'))
            if len(encoding.encode(proposed))<=maximum_tokens:
                chosen.append(item)
            else:omitted+=1
    value=envelope(chosen)
    encoded=json.dumps(value,ensure_ascii=False,separators=(',',':'))
    tokens=len(encoding.encode(encoded))
    if tokens>maximum_tokens:raise ValueError('Even the empty context exceeds its budget')
    for index,item in enumerate(chosen):trace[str(index)]=item['native_refs']
    return {'context':encoded,'tokens':tokens,'selected_facts':len(chosen),'omitted_facts':omitted,
            'rejected':rejected,'native_reference_trace':trace}
