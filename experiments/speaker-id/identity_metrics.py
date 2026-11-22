"""Offline E4 identity accounting only, never speaker inference or authorization.

Inputs are independently labelled, frozen evaluation rows and externally supplied
decisions. This module selects no threshold and cannot activate a profile.
"""
from collections import Counter
from tavi.speaker_evidence import FAMILY,_hash


def _session(value):
    if not isinstance(value,str) or not 1<=len(value)<=128:raise ValueError('Bounded session ID required')
    return value


def evaluate(rows, *, model_sha256,enrollment,development_sessions=()):
    _hash(model_sha256)
    if not isinstance(rows,list) or len(rows)>5000 or not isinstance(enrollment,list) or len(enrollment)>200:
        raise ValueError('Bounded frozen evaluation required')
    used_sessions={_session(s) for s in development_sessions};enrolled=set();used_audio=set()
    for e in enrollment:
        if e.get('person_id') not in FAMILY:raise ValueError('Labelled family enrollment required')
        used_sessions.add(_session(e.get('session_id')));used_audio.add(_hash(e.get('pcm_sha256')));enrolled.add(e['person_id'])
    seen_ids=set();seen_audio=set();counts={p:Counter() for p in sorted(FAMILY)};totals=Counter()
    for r in rows:
        sid=_session(r.get('sample_id'));session=_session(r.get('session_id'));sha=_hash(r.get('pcm_sha256'))
        if sid in seen_ids or sha in seen_audio:raise ValueError('Repeated recordings cannot count as independent evidence')
        if sha in used_audio or session in used_sessions:raise ValueError('Held-out evidence overlaps enrollment or development')
        if r.get('model_sha256')!=model_sha256:raise ValueError('Mixed-model identity decisions')
        seen_ids.add(sid);seen_audio.add(sha)
        kind=r.get('label_kind');person=r.get('person_id');decision=r.get('decision')
        duration=r.get('duration_ms');eligible=r.get('eligible');memory=r.get('memory_authorized')
        if (kind not in ('known','unknown','short','overlap') or decision not in FAMILY|{'unknown'}
                or type(eligible) is not bool or type(memory) is not bool
                or type(duration) is not int or not 0<duration<=30000
                or (kind=='known' and person not in FAMILY) or (kind!='known' and person is not None)
                or (kind=='known' and eligible and not 2000<=duration<=5000)):
            raise ValueError('Independent complete labels and bounded decisions required')
        totals['all']+=1;totals[kind]+=1
        if memory and (kind!='known' or decision=='unknown'):totals['uncertain_memory_violations']+=1
        if decision!='unknown' and (kind!='known' or decision!=person):totals['wrong_all']+=1
        if kind=='known':
            c=counts[person];c['attempted']+=1
            if not eligible:c['ineligible']+=1;continue
            totals['known_eligible']+=1;c['eligible']+=1
            if decision==person:c['correct']+=1;totals['correct']+=1
            elif decision=='unknown':c['abstained']+=1;totals['abstained']+=1
            else:c['wrong']+=1;totals['known_wrong']+=1
        elif kind=='unknown':
            totals['unknown_rejected']+=decision=='unknown'
        elif kind=='overlap':
            totals['overlap_memory_violations']+=memory
            totals['overlap_identified']+=decision!='unknown'
        elif kind=='short':totals['short_rejected']+=decision=='unknown'
    def ratio(a,b):return a/b if b else None
    per_person={p:{**dict(c),'correct_fraction':ratio(c['correct'],c['eligible']),
        'correct_fraction_all_attempted':ratio(c['correct'],c['attempted'])} for p,c in counts.items()}
    coverage=all(counts[p]['eligible']>=25 for p in FAMILY)
    sufficient=(enrolled==FAMILY and coverage and totals['unknown']>=20
                and totals['short']+totals['overlap']>=20 and totals['overlap']>0 and totals['short']>0)
    known_accuracy=ratio(totals['correct'],totals['known_eligible'])
    wrong_known=ratio(totals['known_wrong'],totals['known_eligible'])
    unknown_rejection=ratio(totals['unknown_rejected'],totals['unknown'])
    checks={'known_correct_at_least_90_percent':known_accuracy is not None and known_accuracy>=.9,
        'each_person_at_least_85_percent':all(c['correct_fraction'] is not None and c['correct_fraction']>=.85 for c in per_person.values()),
        'known_confident_wrong_at_most_1_percent':wrong_known is not None and wrong_known<=.01,
        'unknown_rejection_at_least_95_percent':unknown_rejection is not None and unknown_rejection>=.95,
        'no_overlap_personal_memory_authorization':totals['overlap_memory_violations']==0,
        'no_uncertain_personal_memory_authorization':totals['uncertain_memory_violations']==0}
    return {'scope':'offline_identity_subscreen_only','sample_count':len(rows),'counts':dict(totals),'per_person':per_person,
        'known_correct_fraction':known_accuracy,'known_confident_wrong_fraction':wrong_known,
        'all_samples_confident_wrong_fraction':ratio(totals['wrong_all'],totals['all']),
        'unknown_rejection_fraction':unknown_rejection,'coverage_complete':sufficient,'checks':checks,
        'identity_subscreen':'needs_evidence' if not sufficient else 'pass' if all(checks.values()) else 'fail',
        'E4_accepted':False,'recognition_enabled':False,'authorizes_personal_memory':False,
        'remaining_E4':['10multi-person sessions/follow-ups/closure','20side-conversation cases','independent provenance/threshold freeze and human review'],
        'accounting_note':'Known unknown-decisions count against eligible identification coverage. Ineligible attempts remain visible. Wrong known assignments use the eligible-known denominator; unknown examples cannot dilute that rate. Both short and overlap labels are required to represent the combined20case set. Labels/eligibility must be frozen independently of predictions.'}
