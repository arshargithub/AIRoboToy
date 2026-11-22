import unittest

from experiments.memory.typed_dialogue import TypedDialogue
from experiments.memory.typed_lookup import MemorySnapshot


class Encoding:
    def encode(self, text):
        return list(text)


class TypedDialogueTests(unittest.TestCase):
    def setUp(self):
        self.people = {'a': 'Ari', 'b': 'Bo'}

    def dialogue(self, response):
        return TypedDialogue({}, Encoding(), lambda *_: response)

    def plan(self, **kw):
        return {'operation': 'preference', 'reference': 'self', 'person': '', 'slot': 'drink', **kw}

    def test_self_is_bound_by_code_to_actual_speaker(self):
        result = self.dialogue(self.plan()).resolve('What is my favourite drink?', 'a', self.people)
        self.assertEqual(result['request']['subject_id'], 'a')

    def test_model_cannot_supply_audience_or_invent_named_target(self):
        with self.assertRaises(ValueError):
            self.dialogue(self.plan(audience=['b'])).resolve('My drink?', 'a', self.people)
        response = self.plan(reference='named', person='Bo')
        self.assertEqual(self.dialogue(response).resolve('What does Ari prefer?', 'a', self.people)['status'], 'clarify')

    def test_multiple_names_and_unknown_speaker_abstain(self):
        response = self.plan(reference='named', person='Bo')
        self.assertEqual(self.dialogue(response).resolve('What do Ari and Bo prefer?', 'a', self.people)['status'], 'clarify')
        self.assertEqual(self.dialogue(self.plan()).resolve('My drink?', 'unknown', self.people)['status'], 'unknown_identity')

    def test_unsupported_lookup_does_not_call_answer_model(self):
        calls = []
        def request(*args):
            calls.append(args)
            if len(calls) > 1:
                self.fail('No answer generation for unsupported memory')
            return self.plan()
        dialogue = TypedDialogue({}, Encoding(), request)
        result = dialogue.respond('My drink?', 'a', MemorySnapshot(self.people, [], []),
                                  audience=['a'], as_of='2026-01-01T00:00:00Z')
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['answer']['source_ids'], [])


if __name__ == '__main__':
    unittest.main()
