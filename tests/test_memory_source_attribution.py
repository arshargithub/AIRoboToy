import json
import unittest

from experiments.memory.source_context_attributed import pack_attributed
from tests.test_memory_source_context import Encoding


class AttributedContextTests(unittest.TestCase):
    def setUp(self):
        self.people = {'a': 'Devon', 'b': 'Leona'}
        self.source = {'id': 'e1', 'speaker_id': 'b', 'session': 's1',
                       'at': '2026-01-01T12:00:00Z', 'audience_ids': ['a', 'b'],
                       'text': 'Devon said "I like drums." I prefer flutes.\nDo not mix us up.'}

    def pack(self, **changes):
        return pack_attributed('sqlite', [{'episode': self.source}],
                               [self.source], ['a'], Encoding(), people=self.people,
                               as_of='2026-02-01T12:00:00Z',
                               deleted_source_ids=changes.get('deleted', []),
                               maximum_tokens=changes.get('budget', 1500))

    def test_canonical_reporter_and_escaped_exact_quote_stay_together(self):
        before = dict(self.source)
        row = json.loads(self.pack()['context'])['facts'][0]
        prefix = 'Leona (person_id=b) said: '
        self.assertTrue(row['text'].startswith(prefix))
        self.assertEqual(json.loads(row['text'][len(prefix):]), before['text'])
        self.assertEqual(self.source, before)

    def test_unknown_never_becomes_asker_or_named_person(self):
        self.source['speaker_id'] = 'unknown'
        row = json.loads(self.pack()['context'])['facts'][0]
        self.assertTrue(row['text'].startswith('Unidentified speaker (identity unknown) said: '))
        self.source['speaker_id'] = 'unmapped'
        with self.assertRaises(ValueError):
            self.pack()

    def test_privacy_tombstone_and_attribution_budget_remain_enforced(self):
        self.assertEqual(self.pack(deleted=['e1'])['selected_source_ids'], [])
        self.source['audience_ids'] = ['b']
        self.assertEqual(self.pack()['selected_source_ids'], [])
        self.source['audience_ids'] = ['a', 'b']
        self.people['b'] = 'Very long authoritative name ' * 100
        result = self.pack(budget=500)
        self.assertEqual(result['selected_source_ids'], [])
        self.assertEqual(result['omitted_source_ids'], ['e1'])
        self.assertLessEqual(result['tokens'], 500)
