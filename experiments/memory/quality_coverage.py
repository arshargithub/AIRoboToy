"""Offline coverage accounting over frozen questions and existing explicit labels.

Does not generate labels, change historical criteria, rank engines or accept E5.
"""
from collections import Counter

FIELDS=('task_correct','all_claims_grounded','privacy_violation','identity_error',
        'unsupported_strong_pattern_claim','warranted_pattern_recalled')


def summarize(corpus,queries,labels):
    expected={q['id']:q for q in corpus['questions']}
    if len(expected)!=len(corpus['questions']) or not expected:raise ValueError('Unique frozen questions required')
    if not isinstance(labels,dict) or set(labels)-set(expected):raise ValueError('Review contains unknown questions')
    observed={}
    for q in queries:
        question=q['question'];qid=question['id']
        if qid in observed or qid not in expected:raise ValueError('Duplicate or unexpected collected question')
        if question!=expected[qid]:raise ValueError('Collected question differs from frozen corpus')
        observed[qid]=q
    if set(labels)-set(observed):raise ValueError('Review has no matching collected answer')
    categories={};failures=[]
    for qid,q in expected.items():
        c=categories.setdefault(q['category'],Counter());c['expected']+=1
        row=observed.get(qid);label=labels.get(qid)
        if row is None:failures.append({'id':qid,'reason':'missing_answer'});continue
        c['collected']+=1
        text=row.get('answer',{}).get('text')
        if label is None:failures.append({'id':qid,'reason':'missing_review'});continue
        if any(type(label.get(k)) is not bool for k in FIELDS) or not isinstance(label.get('rationale'),str) or not label['rationale'].strip():
            raise ValueError('Every saved label needs explicit Booleans and rationale')
        c['reviewed']+=1
        if not isinstance(text,str) or not text.strip():
            if label['task_correct'] or label['all_claims_grounded']:raise ValueError('Empty answer cannot be credited')
            failures.append({'id':qid,'reason':'empty_answer'});continue
        correct=label['task_correct'] and label['all_claims_grounded']
        c['task_and_grounding_correct']+=correct
        for field in ('privacy_violation','identity_error','unsupported_strong_pattern_claim'):c[field]+=label[field]
        if not correct:failures.append({'id':qid,'reason':'reviewed_task_or_grounding_failure'})
    total=sum(c['expected'] for c in categories.values());correct=sum(c['task_and_grounding_correct'] for c in categories.values())
    complete=len(observed)==len(labels)==total
    def aggregate(names):
        selected=[c for name,c in categories.items() if name in names];n=sum(c['expected'] for c in selected)
        k=sum(c['task_and_grounding_correct'] for c in selected)
        return {'correct':k,'expected':n,'rate':k/n if n and complete else None}
    return {'expected':total,'collected':len(observed),'reviewed':len(labels),'complete':complete,
        'all_question_task_and_grounding':{'correct':correct,'expected':total,'rate':correct/total if complete else None},
        'nonpattern_task_and_grounding':aggregate(set(categories)-{'pattern'}),
        'legacy_direct_fact_subset':aggregate({'factual','correction'}),
        'per_category':{name:{**dict(c),'rate':c['task_and_grounding_correct']/c['expected'] if complete else None} for name,c in categories.items()},
        'failures':failures,'full_E5_accepted':False,
        'interpretation':'All-question and nonpattern figures are supplemental historical diagnostics. Legacy direct-fact metric is a subset, not overall quality. New acceptance metrics need prospective freezing, native profile/durability/timing/three-repeat gates and independent source review.'}
