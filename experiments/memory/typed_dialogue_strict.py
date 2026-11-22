"""Same dialogue semantics with provider-enforced JSON schema contracts."""
import json

from experiments.memory.runtime import MODEL
from experiments.memory.typed_dialogue import TypedDialogue, RESOLVE, COMPOSE

ROUTE_SCHEMA = {'type': 'object', 'properties': {
    'operation': {'type': 'string', 'enum': ['preference', 'interests', 'events', 'clarify', 'none']},
    'reference': {'type': 'string', 'enum': ['self', 'named', 'unknown']},
    'person': {'type': 'string'}, 'slot': {'type': 'string'}},
    'required': ['operation', 'reference', 'person', 'slot'], 'additionalProperties': False}
ANSWER_SCHEMA = {'type': 'object', 'properties': {
    'text': {'type': 'string'}, 'source_ids': {'type': 'array', 'items': {'type': 'string'}}},
    'required': ['text', 'source_ids'], 'additionalProperties': False}


class StrictTypedDialogue(TypedDialogue):
    def __init__(self, broker, encoding, trace_callback=None, *, model=MODEL):
        self.model = model
        self.broker = broker
        self.trace_callback = trace_callback or (lambda value: None)
        super().__init__(broker, encoding, self._strict_request)

    def _strict_request(self, instructions, payload):
        import httpx
        if instructions == RESOLVE:
            name, schema = 'memory_route', ROUTE_SCHEMA
        elif instructions == COMPOSE:
            name, schema = 'memory_answer', ANSWER_SCHEMA
        else:
            raise ValueError('Unknown structured output contract')
        response = httpx.post(self.broker['base_url'] + '/sqlite/v1/chat/completions',
            headers={'Authorization': 'Bearer ' + self.broker['token']}, json={
                'model': self.model, 'messages': [{'role': 'system', 'content': instructions},
                    {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}],
                'response_format': {'type': 'json_schema', 'json_schema': {
                    'name': name, 'strict': True, 'schema': schema}},
                'max_completion_tokens': 2048, 'temperature': 0, 'store': False}, timeout=100)
        response.raise_for_status()
        result = response.json()
        choice = result['choices'][0]
        self.trace_callback({'contract': name, 'payload': payload, 'choice': choice,
                             'usage': result.get('usage'), 'model': result.get('model')})
        if result.get('model') != self.model:
            raise ValueError('Unexpected returned model; no publication')
        if choice['finish_reason'] != 'stop' or choice['message'].get('refusal'):
            raise ValueError('Incomplete or refused structured response; no publication')
        return json.loads(choice['message']['content'])
