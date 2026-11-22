"""Experimental single-call decision receipt, with structural—not semantic—checks.

Does not modify stored episodes, infer identity, or grant new audience access.
A reference is not entailment. Free-text fidelity requires separate qualification.
"""
import hashlib
import json
from experiments.memory.companion_contract import MISSION

DECISION_MISSION = MISSION + '''
Return a decision receipt alongside your short conversational text. recipient_id
is the person this response helps, which can differ from the actual speaker.
Use mode listen when only listening is requested, clarify for unresolved recipients,
and suggest otherwise. A memory_use records a zero-based index into memory_evidence.facts
and the subject of the assertion you use, not necessarily the original reporter.
For catalogue tasks, list the items you recommend and any items you explicitly exclude.
For an exclusion, record whose history causes it; do not apply someone else's ownership
or reading history to the recipient. A request to repeat, reread or replace can make an
owned/completed item appropriate. List relevant supporting fact indices; do not cite an
irrelevant fact merely to fill the receipt. New suggestions need not have been requested
before. Use only supplied catalogue properties, keeping unknown properties unknown.
Your text must faithfully express this decision, without exposing this internal record.
No recipient clarification or private-memory access is authorized by a model-produced ID.
'''


def obj(properties):
    return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}


def array(items):return {'type':'array','items':items}

IDS=array({'type':'integer'})
SCHEMA=obj({
    'recipient_id':{'type':['string','null']},
    'mode':{'type':'string','enum':['suggest','listen','clarify']},
    'memory_uses':array(obj({'fact_index':{'type':'integer'},'subject_id':{'type':'string'}})),
    'recommendations':array(obj({'item_id':{'type':'string'},'fact_indices':IDS})),
    'exclusions':array(obj({'item_id':{'type':'string'},'subject_id':{'type':'string'},'fact_indices':IDS})),
    'text':{'type':'string'},
})


def snapshot(task, evidence):
    return hashlib.sha256(json.dumps({'task':task,'evidence':evidence},sort_keys=True,
                                    separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def validate(value, task, evidence, *, issued_snapshot, current_snapshot):
    """Return receipt only when exact request/context and references are consistent.

    Subject membership and exclusion-recipient equality are checkable. Whether a
    fact is really about the claimed subject, or supports text, is NOT proved here.
    """
    if issued_snapshot!=current_snapshot or snapshot(task,evidence)!=issued_snapshot:
        raise ValueError('Stale task or memory evidence; do not publish')
    people=task['people'];speaker=task['actual_speaker_id'];audience=task['audience_ids']
    if speaker not in people or speaker not in audience or not audience or not set(audience)<=set(people):
        raise ValueError('Unqualified identity or audience; no personal response')
    if not isinstance(value,dict) or set(value)!=set(SCHEMA['properties']):raise ValueError('Invalid receipt fields')
    target=value['recipient_id'];mode=value['mode']
    if mode not in ('suggest','listen','clarify') or target is not None and target not in people:
        raise ValueError('Invalid recipient or mode')
    if mode!='clarify' and target is None:raise ValueError('Unresolved recipient')
    if not isinstance(value['text'],str) or not value['text'].strip() or len(value['text'])>1600:
        raise ValueError('Invalid reply text')
    facts=evidence.get('facts',[]);headers=evidence.get('source_headers',{})
    catalogue={i['id']:i for i in task['catalogue']}
    if len(catalogue)!=len(task['catalogue']):raise ValueError('Duplicate catalogue IDs')
    def check_indices(indices):
        if (not isinstance(indices,list) or len(indices)>20 or any(type(i)!=int or not 0<=i<len(facts) for i in indices)
                or len(indices)!=len(set(indices))):raise ValueError('Invalid evidence indices')
        for i in indices:
            sources=facts[i].get('sources',[])
            if not sources or any(s not in headers or headers[s]['speaker_id'] not in people for s in sources):
                raise ValueError('Unqualified cited source')
    for field in ['memory_uses','recommendations','exclusions']:
        if not isinstance(value[field],list) or len(value[field])>20:raise ValueError('Unbounded receipt')
    for use in value['memory_uses']:
        if set(use)!={'fact_index','subject_id'} or use['subject_id'] not in people:raise ValueError('Invalid memory subject')
        check_indices([use['fact_index']])
    for field in ['recommendations','exclusions']:
        seen=set()
        for item in value[field]:
            expected={'item_id','fact_indices'} | ({'subject_id'} if field=='exclusions' else set())
            if set(item)!=expected or item['item_id'] not in catalogue or item['item_id'] in seen:
                raise ValueError('Invalid catalogue reference')
            seen.add(item['item_id']);check_indices(item['fact_indices'])
            if field=='exclusions' and item['subject_id']!=target:
                raise ValueError('Exclusion belongs to another recipient')
    if {i['item_id'] for i in value['recommendations']} & {i['item_id'] for i in value['exclusions']}:
        raise ValueError('Item both recommended and excluded')
    if mode in ('listen','clarify') and any(value[k] for k in ['memory_uses','recommendations','exclusions']):
        raise ValueError('Listening/clarification must not carry hidden personal recommendations')
    return {'text':value['text'],'receipt':value,'structural_check_passed':True,
            'semantic_grounding_verified':False,'snapshot':issued_snapshot}
