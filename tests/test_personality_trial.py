import json
import unittest
from unittest.mock import Mock

from experiments.memory.personality_trial import PromptReference, BoundedLedger, review_packets
from experiments.memory.native_voice import response_options


class Wire:
    async def send(self, text):
        self.message=json.loads(text)


class PromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_override_only_instruction_on_actual_wire(self):
        client=PromptReference(Mock(),'FROZEN CANDIDATE')
        client.ws=Wire()
        task={'actual_speaker_id':'anonymous','audience_ids':['anonymous'],
              'people':{'anonymous':'Unknown'},'question':'hello'}
        original=response_options(task,{'facts':[]},'case')
        original['output_modalities']=['text']
        await client.send('response.create',response=original)
        wire=client.ws.message['response']
        self.assertEqual(wire['instructions'],'FROZEN CANDIDATE')
        self.assertNotEqual(original['instructions'],'FROZEN CANDIDATE')
        for key in original:
            if key!='instructions':self.assertEqual(original[key],wire[key])
        self.assertEqual(client.wire_request,wire)

    async def test_session_update_not_overridden(self):
        client=PromptReference(Mock(),'FROZEN CANDIDATE');client.ws=Wire()
        await client.send('session.update',session={'instructions':'SESSION'})
        self.assertEqual(client.ws.message['session']['instructions'],'SESSION')
        self.assertIsNone(client.wire_request)


class BudgetTests(unittest.TestCase):
    def test_real_ledger_and_reservation_bound_preserved(self):
        ledger=Mock();ledger.used_micro_usd.return_value=20_000_000
        budget=BoundedLedger(ledger,3_000_000,1)
        budget.reserve('id',1_000_000,25_000_000)
        ledger.reserve.assert_called_once_with('id',1_000_000,23_000_000)
        with self.assertRaises(ValueError):budget.reserve('again',1_000_000,25_000_000)
        budget.settle('id',30_000);ledger.settle.assert_called_once_with('id',30_000)

    def test_project_cap_is_never_widened(self):
        ledger=Mock();ledger.used_micro_usd.return_value=24_000_000
        BoundedLedger(ledger,3_000_000,40).reserve('id',1_000_000,25_000_000)
        ledger.reserve.assert_called_once_with('id',1_000_000,25_000_000)


class ReviewBoundaryTests(unittest.TestCase):
    def test_regression_cannot_inflate_fresh_denominator_or_style_wins(self):
        cases=[{'id':'fresh','required':'answer','task':{'question':'Q'},'style_case':True},
               {'id':'old','required':'answer','cohort':'regression'}]
        rows=[{'case_id':'fresh','arm':a,'reply':{'text':a}} for a in ['baseline','candidate']]
        rows.append({'case_id':'old','arm':'candidate','reply':{'text':'old'}})
        packet,regressions,mapping=review_packets(cases,rows,1)
        self.assertEqual([r['case_id'] for r in packet],['fresh'])
        self.assertEqual([r['case_id'] for r in regressions],['old'])
        self.assertEqual(set(mapping),{'fresh'})

    def test_partial_pair_or_duplicate_arm_cannot_be_reviewed_as_complete(self):
        cases=[{'id':'fresh','required':'answer','task':{'question':'Q'},'style_case':True}]
        row={'case_id':'fresh','arm':'candidate','reply':{'text':'answer'}}
        for rows in [[row],[row,row]]:
            with self.assertRaises(ValueError):review_packets(cases,rows,1)
