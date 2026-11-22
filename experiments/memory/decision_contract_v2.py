"""Repaired receipt contract: per-item subjects; memory can inform listening.

Structural integrity only. Semantic grounding and prose fidelity remain measured.
"""
from experiments.memory.decision_contract import obj,array,IDS,snapshot
from experiments.memory.companion_contract import MISSION

DECISION_MISSION=MISSION+'''
Alongside your conversational text, return a compact evidence receipt.
Each memory_use identifies a zero-based memory_evidence.facts index and the person
that assertion is about. This is not necessarily its reporter or the current speaker.
Memory may inform understanding or listening without becoming an activity suggestion.
For supplied catalogue items that you recommend or explicitly reject, return
catalogue_choices with item_id, disposition, for_person_id and supporting fact_indices.
for_person_id is whose interests, ownership or reading history makes THAT choice
appropriate or inappropriate: for a gift, the gift recipient, not the buyer.
Use null when giving generic advice for an unknown person. No personal memory claim
may be made about that unknown person, but generic catalogue suggestions are welcome.
Include only supplied catalogue IDs; when there is no catalogue, catalogue_choices
must be empty. Activities and other open-ended ideas stay in the text and can have
memory_uses; never invent catalogue IDs for them. A person having read an item does
not establish whether another person has read it or whether either person owns it.
Preserve explicit repeat/replacement requests. Exclude only at the supported scope.
The text must agree with this receipt, without showing it or exposing internal IDs.
'''
SCHEMA=obj({'memory_uses':array(obj({'fact_index':{'type':'integer'},'subject_id':{'type':'string'}})),
            'catalogue_choices':array(obj({'item_id':{'type':'string'},'disposition':{'type':'string','enum':['recommend','exclude']},
                                         'for_person_id':{'type':['string','null']},'fact_indices':IDS})),
            'text':{'type':'string'}})


def validate(value,task,evidence,*,issued_snapshot,current_snapshot):
    if issued_snapshot!=current_snapshot or snapshot(task,evidence)!=issued_snapshot:
        raise ValueError('Stale task or evidence')
    people=task['people'];aud=task['audience_ids'];speaker=task['actual_speaker_id']
    if not aud or not set(aud)<=set(people) or speaker not in people or speaker not in aud:
        raise ValueError('Unqualified identity/audience')
    if not isinstance(value,dict) or set(value)!=set(SCHEMA['properties']):raise ValueError('Invalid receipt')
    if not isinstance(value['text'],str) or not value['text'].strip() or len(value['text'])>1600:raise ValueError('Invalid reply')
    for field in ['memory_uses','catalogue_choices']:
        if not isinstance(value[field],list) or len(value[field])>20:raise ValueError('Unbounded receipt')
    facts=evidence.get('facts',[]);headers=evidence.get('source_headers',{})
    catalogue={x['id'] for x in task['catalogue']}
    if len(catalogue)!=len(task['catalogue']):raise ValueError('Ambiguous catalogue IDs')
    def indices(xs):
        if (not isinstance(xs,list) or len(xs)>20 or any(type(x)!=int or not 0<=x<len(facts) for x in xs)
            or len(xs)!=len(set(xs))):raise ValueError('Invalid fact indices')
        for x in xs:
            src=facts[x].get('sources',[])
            if not src or any(s not in headers or headers[s]['speaker_id'] not in people for s in src):
                raise ValueError('Unqualified cited source')
    for use in value['memory_uses']:
        if set(use)!={'fact_index','subject_id'} or use['subject_id'] not in people:raise ValueError('Invalid subject')
        indices([use['fact_index']])
    seen=set()
    for c in value['catalogue_choices']:
        if set(c)!={'item_id','disposition','for_person_id','fact_indices'}:raise ValueError('Invalid choice')
        if c['item_id'] not in catalogue or c['disposition'] not in ('recommend','exclude'):raise ValueError('Invalid catalogue item')
        if c['for_person_id'] is not None and c['for_person_id'] not in people:raise ValueError('Invalid choice subject')
        key=(c['item_id'],c['for_person_id'])
        if key in seen:raise ValueError('Conflicting or duplicate item decision for this person')
        seen.add(key);indices(c['fact_indices'])
        if c['for_person_id'] is None and c['fact_indices']:raise ValueError('Generic choice cannot assign personal evidence to an unknown person')
    return {'text':value['text'],'receipt':value,'structural_check_passed':True,
            'semantic_grounding_verified':False,'snapshot':issued_snapshot}
