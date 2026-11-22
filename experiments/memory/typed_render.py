"""Controlled factual wording; models cannot strengthen pattern/date claims here.

This is an experimental renderer, not open-ended conversational personality.
It preserves source-relative dates inside dated quotations and abstains if the
whole supported result will not fit. No extraction or identity trust is added.
"""
from datetime import datetime

from experiments.memory.typed_dialogue import TypedDialogue, source_ids


def render_memory(route, lookup, speaker, people):
    if route['status'] != 'resolved':
        return None
    subject = route['request']['subject_id']
    possessive = 'your' if subject == speaker else people[subject] + "'s"
    target = 'you' if subject == speaker else people[subject]
    status = lookup['status']
    if status in {'unknown', 'unknown_identity', 'pending', 'uncertain', 'conflict', 'withdrawn'}:
        return {'text': "I don't have a reliable memory of that yet.", 'source_ids': []}
    operation = route['request']['operation']
    ids = set()
    if operation == 'preference' and status == 'supported':
        slot = route['request']['slot']
        text = f"I remember {lookup['value']} as {possessive} preferred {slot}."
        ids.update(lookup['source_ids'])
    elif operation == 'interests' and status == 'evaluated':
        statements = []
        for row in lookup['patterns']:
            activity = row['activity']; state = row['status']
            if state == 'tentative':
                statements.append(f"{activity.capitalize()} might be an interest of {('yours' if subject == speaker else people[subject] + chr(39) + 's')}; I have choices from {row['session_count']} different conversations.")
            elif state == 'withdrawn':
                statements.append(f"I won't suggest {activity} based on {possessive} old choices; I have a note to stop recommending it.")
            elif state == 'insufficient_sessions':
                statements.append(f"I have {possessive} {activity} choices from {row['session_count']} different conversation(s), which isn't enough to call it a pattern yet.")
            elif state == 'conflict':
                statements.append(f"I'm not sure whether {activity} is still an interest for {target}.")
            else:
                raise ValueError('Unknown interest status; no publication')
            ids.update(row.get('source_ids', []))
        text = ' '.join(statements) or "I haven't noticed a reliable pattern yet."
    elif operation == 'events' and status == 'supported':
        statements = []
        for event in lookup['events']:
            date = datetime.fromisoformat(event['reported_at'].replace('Z', '+00:00')).strftime('%B %d, %Y')
            who = 'you' if event['speaker_id'] == speaker else people[event['speaker_id']]
            statements.append(f'On {date}, {who} said: “{event["quote"]}”')
            ids.add(event['source_id'])
        text = ' '.join(statements)
    else:
        raise ValueError('Unknown memory status; no publication')
    if not text or len(text) > 2000 or not ids <= source_ids(lookup):
        raise ValueError('Unbounded or ungrounded rendered result; no publication')
    return {'text': text, 'source_ids': sorted(ids)}


class RenderedTypedDialogue(TypedDialogue):
    def __init__(self, resolver, encoding):
        super().__init__({}, encoding, resolver.request)

    def respond(self, question, speaker, snapshot, *, audience, as_of):
        import json
        route = self.resolve(question, speaker, snapshot.people)
        if route['status'] != 'resolved':
            return {'route': route, 'lookup': None, 'answer': None,
                    'next_action': 'general_conversation' if route['status'] == 'none' else 'ask_clarification'}
        lookup = snapshot.lookup(route['request'], audience=audience, as_of=as_of)
        if len(self.encoding.encode(json.dumps(lookup))) > 1500:
            raise ValueError('Typed context exceeds1500 tokens')
        return {'route': route, 'lookup': lookup,
                'answer': render_memory(route, lookup, speaker, snapshot.people), 'next_action': 'continue'}
