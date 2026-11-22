import copy
import json
from pathlib import Path
import unittest
from experiments.memory.reply_boundary import qualify_context


class ReplyBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.task = {'people': {'a': 'A', 'b': 'B'}, 'actual_speaker_id': 'a', 'audience_ids': ['a', 'b']}
        self.source = {'id': 's', 'speaker_id': 'a', 'session': 'v', 'at': '2026-01-01T00:00:00Z',
                       'audience_ids': ['a', 'b'], 'text': 'I like reading because it is quiet.'}
        self.evidence = {'source_headers': {'s': {'speaker_id': 'b'}},
                         'facts': [{'text': self.source['text'], 'sources': ['s']}]}

    def test_preserves_full_text_and_uses_canonical_metadata(self):
        out = qualify_context(self.task, self.evidence, [self.source])
        self.assertEqual(out['evidence']['facts'], self.evidence['facts'])
        self.assertEqual(out['evidence']['source_headers']['s']['speaker_id'], 'a')
        self.assertFalse(out['semantic_grounding_verified'])

    def test_mixed_support_is_dropped_whole(self):
        self.evidence['facts'][0]['sources'].append('unknown-source')
        self.assertFalse(qualify_context(self.task, self.evidence, [self.source])['evidence']['facts'])

    def test_private_deleted_unknown_and_unresolved_support_blocked(self):
        for change in [{'audience_ids': ['a']}, {'deleted': True}, {'speaker_id': 'unknown'}, {'quarantined': True}]:
            with self.subTest(change=change):
                self.assertFalse(qualify_context(self.task, self.evidence, [{**self.source, **change}])['evidence']['facts'])
        self.evidence['facts'][0]['unresolved_support'] = ['missing']
        self.assertFalse(qualify_context(self.task, self.evidence, [self.source])['evidence']['facts'])

    def test_unknown_audience_and_duplicate_source_fail_closed(self):
        with self.assertRaises(ValueError):
            qualify_context(self.task, self.evidence, [self.source, self.source])
        with self.assertRaises(ValueError):
            qualify_context({**self.task, 'audience_ids': ['unknown']}, self.evidence, [self.source])

    def test_real_legacy_contamination_removes_both_derived_unknown_assertions(self):
        root = Path(__file__).resolve().parents[1]
        case = json.loads((root/'experiments/memory/decision-v2-input.json').read_text())['regressions'][0]
        sources = json.loads((root/'experiments/memory/companion-input-v1.json').read_text())['episodes']
        before = copy.deepcopy(case)
        out = qualify_context(case['task'], case['memory_evidence'], sources)
        self.assertEqual([x['original_index'] for x in out['rejected']], [0, 3])
        self.assertNotIn('u013', out['evidence']['source_headers'])
        self.assertEqual(out['evidence']['facts'][2], case['memory_evidence']['facts'][4])
        self.assertEqual(case, before)
