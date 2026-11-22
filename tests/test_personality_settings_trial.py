import copy
import json
import unittest
from unittest.mock import patch

from experiments.memory.personality_settings_trial import (
    SettingsReference, budget_preflight, BudgetApprovalRequired)
from tavi.realtime_reference import session_config


class Socket:
    def __init__(self, mutate=None):
        self.queue = [{'type':'session.created'}]
        self.sent = []
        self.mutate = mutate

    async def send(self, raw):
        event = json.loads(raw); self.sent.append(event)
        if event['type']=='session.update':
            cfg = copy.deepcopy(event['session'])
            if len(self.sent)==2 and self.mutate:
                self.mutate(cfg)
            self.queue.append({'type':'session.updated','session':cfg})

    async def recv(self):
        return json.dumps(self.queue.pop(0))


class SettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_arms_use_same_updates_and_expected_receipts(self):
        wires = []
        for effort in ['minimal','low']:
            wire = Socket(); wires.append(wire)
            async def connector():return wire
            ref = SettingsReference(None,'FROZEN',effort,connector=connector)
            await ref.connect()
            self.assertEqual(ref.session['reasoning'],{'effort':effort})
            self.assertEqual(len(wire.sent),2)
            self.assertEqual([e['type'] for e in wire.sent],['session.update']*2)
        left,right=[w.sent[-1]['session'] for w in wires]
        self.assertEqual({k:v for k,v in left.items() if k!='reasoning'},
                         {k:v for k,v in right.items() if k!='reasoning'})
        self.assertEqual(session_config()['reasoning'],{'effort':'minimal'})

    async def test_wrong_settings_are_rejected_before_any_response_request(self):
        for key,value in [('reasoning',{'effort':'minimal'}),('model','wrong'),
                          ('tools',[{'type':'function'}]),('max_output_tokens',999)]:
            def mutate(cfg):cfg[key]=value
            wire = Socket(mutate)
            async def connector():return wire
            ref = SettingsReference(None,'FROZEN','low',connector=connector)
            with self.assertRaises(ValueError):await ref.connect()
            self.assertFalse(any(e['type']=='response.create' for e in wire.sent))

    async def test_auto_generation_is_rejected(self):
        def mutate(cfg):cfg['audio']['input']['turn_detection']={'type':'server_vad'}
        wire = Socket(mutate)
        async def connector():return wire
        ref = SettingsReference(None,'FROZEN','low',connector=connector)
        with self.assertRaises(ValueError):await ref.connect()

    async def test_undeclared_effort_is_not_allowed(self):
        with self.assertRaises(ValueError):SettingsReference(None,'FROZEN','medium')


class FundingTests(unittest.TestCase):
    def plan(self):
        return {'configuration':{'required_project_cap_micro_usd':27_000_000,
                  'shared_anchor_micro_usd':23_616_124,'maximum_combined_micro_usd':3_250_000},
                'limits':{'maximum_additional_api_usd':2.0}}

    def test_existing_cap_blocks_collection_without_changing_it(self):
        with patch('experiments.memory.personality_settings_trial.APPROVED_BUDGET_MICRO_USD',25_000_000):
            with self.assertRaises(BudgetApprovalRequired):budget_preflight(self.plan(),23_616_124)

    def test_approved_project_stage_and_combined_caps_all_apply(self):
        with patch('experiments.memory.personality_settings_trial.APPROVED_BUDGET_MICRO_USD',27_000_000):
            self.assertEqual(budget_preflight(self.plan(),23_616_124),25_616_124)
            self.assertEqual(budget_preflight(self.plan(),25_000_000),26_866_124)
            with self.assertRaises(BudgetApprovalRequired):budget_preflight(self.plan(),26_000_000)

    def test_ledger_reset_or_removal_of_uncertain_reservations_is_not_accepted(self):
        with patch('experiments.memory.personality_settings_trial.APPROVED_BUDGET_MICRO_USD',27_000_000):
            with self.assertRaises(ValueError):budget_preflight(self.plan(),20_000_000)
