import json
import unittest
from unittest.mock import Mock, patch

from experiments.memory.runtime import MODEL, CAPACITY_MODEL
from experiments.memory.typed_dialogue import RESOLVE
from experiments.memory.typed_dialogue_strict import StrictTypedDialogue


class StrictDialogueTests(unittest.TestCase):
    def test_schema_is_strict_and_semantic_guards_remain(self):
        answer = {'operation': 'preference', 'reference': 'named', 'person': 'Bo', 'slot': 'drink'}
        result = Mock()
        result.json.return_value = {'model': MODEL, 'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(answer)}}]}
        trace = []
        client = StrictTypedDialogue({'base_url': 'http://127.0.0.1:1', 'token': 'test'}, None, trace.append)
        with patch('httpx.post', return_value=result) as post:
            route = client.resolve('What does Ari prefer?', 'a', {'a': 'Ari', 'b': 'Bo'})
        schema = post.call_args.kwargs['json']['response_format']['json_schema']
        self.assertTrue(schema['strict'])
        self.assertNotIn('preferences', schema['schema']['properties']['operation']['enum'])
        self.assertEqual(route['status'], 'clarify')
        self.assertEqual(trace[0]['choice']['message']['content'], json.dumps(answer))

    def test_refusal_and_truncation_do_not_publish(self):
        client = StrictTypedDialogue({'base_url': 'http://127.0.0.1:1', 'token': 'test'}, None)
        for choice in [{'finish_reason': 'length', 'message': {'content': '{}'}},
                       {'finish_reason': 'stop', 'message': {'refusal': 'Refused', 'content': None}}]:
            response = Mock();response.json.return_value = {'model': MODEL, 'choices': [choice]}
            with patch('httpx.post', return_value=response), self.assertRaises(ValueError):
                client._strict_request(RESOLVE, {})

    def test_wrong_returned_model_is_not_published(self):
        client = StrictTypedDialogue({'base_url': 'http://127.0.0.1:1', 'token': 'test'}, None,
                                     model=CAPACITY_MODEL)
        response = Mock()
        response.json.return_value = {'model': MODEL, 'choices': [
            {'finish_reason': 'stop', 'message': {'content': '{}'}}]}
        with patch('httpx.post', return_value=response), self.assertRaises(ValueError):
            client._strict_request(RESOLVE, {})
