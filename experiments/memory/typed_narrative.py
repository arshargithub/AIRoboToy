"""Warm, source-bound recall with scoped history and report-relative time.

Counts stay in policy; wording never turns choices into invented discussions,
causes or confidence. This candidate is separate from sealed renderer v1.
"""
from datetime import datetime
import json

from experiments.memory.subject_contract import eligible
from experiments.memory.source_context import timestamp
from experiments.memory.typed_dialogue import source_ids
from experiments.memory.typed_route_guard import GuardedRenderedDialogue


def elapsed_report(reported_at, as_of):
    then, now = timestamp(reported_at), timestamp(as_of)
    if then > now:raise ValueError('Future report cannot be recalled')
    days=(now.date()-then.date()).days
    if days == 0:return 'earlier today'
    if days == 1:return 'yesterday'
    if days < 7:return f'{days} days ago'
    if days < 14:return 'about a week ago'
    if days < 28:return f'about {round(days/7)} weeks ago'
    if days < 45:return 'about a month ago'
    if days < 345:return f'about {max(2,round(days/30.44))} months ago'
    if days < 548:return 'about a year ago'
    return f'about {round(days/365.25)} years ago'


def narrative_lookup(snapshot, request, *, audience, as_of):
    result=snapshot.lookup(request,audience=audience,as_of=as_of)
    if request['operation'] != 'preference' or result['status'] not in {'supported','withdrawn'}:
        return result
    rows=eligible(snapshot.claims,snapshot.sources,snapshot.admissions,
                  subject=request['subject_id'],slot=request['slot'],audience=audience,
                  as_of=as_of,deleted_source_ids=snapshot.deleted)
    preferences=[(c,s) for c,s in rows if c.kind=='preference']
    if not preferences:return result
    cutoff=timestamp(result['observed_at']) if result['status']=='supported' else max(
        timestamp(snapshot.ledger[sid]['at']) for sid in result['source_ids'])
    older=[(c,s) for c,s in preferences if timestamp(s['at'])<cutoff]
    if not older:return result
    newest=max(timestamp(s['at']) for _,s in older)
    latest=[(c,s) for c,s in older if timestamp(s['at'])==newest]
    if len({c.value for c,_ in latest})!=1:return result
    value=latest[0][0].value
    if result['status']=='supported' and value==result['value']:return result
    # A later unresolved correction may make this historical state ambiguous.
    # The base lookup protects current state, but history needs its own check.
    if any(c.subject_id==request['subject_id'] and c.slot==request['slot']
           and c.kind in {'preference','withdraw'}
           and snapshot.authorized(snapshot.ledger[c.source_id],audience,as_of)
           and newest <= timestamp(snapshot.ledger[c.source_id]['at']) < cutoff
           for c in snapshot.unresolved):return result
    return {**result,'previous_preference':{'value':value,
        'source_ids':sorted({s['id'] for _,s in latest}), 'reported_at':newest.isoformat()}}


def render_narrative(route, lookup, speaker, people, *, as_of):
    if route['status']!='resolved':return None
    subject=route['request']['subject_id'];own=subject==speaker
    person='you' if own else people[subject]
    possessive='your' if own else people[subject]+"'s"
    status=lookup['status'];operation=route['request']['operation'];ids=set()
    if status in {'unknown','unknown_identity','pending','uncertain','conflict'}:
        return {'text':"I'm not sure about that yet. Can you remind me?",'source_ids':[]}
    if operation=='preference':
        previous=lookup.get('previous_preference')
        if status=='supported':
            text=f"{lookup['value'][0].upper()+lookup['value'][1:]}! That's the latest favourite {route['request']['slot']} I remember for {person}."
            if previous:
                text=f"I remember {previous['value']} from before, but now I have {lookup['value']} as {possessive} favourite {route['request']['slot']}."
        elif status=='withdrawn':
            text=(f"I remember {previous['value']} was {possessive} favourite {route['request']['slot']}, but it isn't anymore."
                  if previous else f"I remember {possessive} favourite {route['request']['slot']} changed.")
            if own:text+=' Have you found a new favourite?'
        else:raise ValueError('Unknown preference state')
        ids.update(lookup['source_ids'])
        if previous:ids.update(previous['source_ids'])
    elif operation=='interests' and status=='evaluated':
        statements=[]
        for row in lookup['patterns']:
            activity=row['activity'];state=row['status'];subject_text='You' if own else people[subject]
            if state=='tentative':
                statements.append(f"{subject_text} {('have' if own else 'has')} picked {activity} a few times. Maybe that would be fun to do again?")
            elif state=='withdrawn':
                statements.append(f"Let's try something other than {activity} this time.")
            elif state=='insufficient_sessions':
                if row['session_count']:
                    statements.append(f"{subject_text} picked {activity}, but I'm not sure it's becoming a favourite yet.")
                else:continue
            elif state=='conflict':
                statements.append(f"I'm not sure whether {person} still {('enjoy' if own else 'enjoys')} {activity}.")
            else:raise ValueError('Unknown pattern state')
            ids.update(row.get('source_ids',[]))
        text=' '.join(statements) or 'What sounds fun today? We could try something new.'
    elif operation=='events' and status=='supported':
        statements=[]
        for event in lookup['events']:
            who='you' if event['speaker_id']==speaker else people[event['speaker_id']]
            ago=elapsed_report(event['reported_at'],as_of)
            # Elapsed time qualifies the REPORT, not an inferred event date.
            statements.append(f'I remember {who} saying {ago}: “{event["quote"]}”')
            ids.add(event['source_id'])
        text=' '.join(statements)
    else:raise ValueError('Unknown memory operation/state')
    if not text or len(text)>2000 or not ids<=source_ids(lookup):
        raise ValueError('Unbounded or unsupported narrative result')
    return {'text':text,'source_ids':sorted(ids)}


class NarrativeDialogue(GuardedRenderedDialogue):
    def respond(self, question, speaker, snapshot, *, audience, as_of):
        route=self.resolve(question,speaker,snapshot.people)
        if route['status']!='resolved':
            return {'route':route,'lookup':None,'answer':None,
                    'next_action':'general_conversation' if route['status']=='none' else 'ask_clarification'}
        lookup=narrative_lookup(snapshot,route['request'],audience=audience,as_of=as_of)
        if len(self.encoding.encode(json.dumps(lookup)))>1500:raise ValueError('Memory context exceeds1500 tokens')
        return {'route':route,'lookup':lookup,'answer':render_narrative(route,lookup,speaker,snapshot.people,as_of=as_of),'next_action':'continue'}
