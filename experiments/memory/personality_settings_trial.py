"""Owner-requested organisation, then effort contrasts. No production changes.

Both stages require explicit increased-budget authority before collection.
No microphone, history export, household bank, voice synthesis or deployment.
"""
import argparse
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import time

from experiments.memory.personality_trial import PromptReference, BoundedLedger, review_packets
from tavi.realtime_reference import MODEL, VOICE, RESERVATION, session_config
from tavi.storage import Store, APPROVED_BUDGET_MICRO_USD
from tavi.experiment_workflow import ROOT, begin, read_protocol, discover_runs, audit


class BudgetApprovalRequired(ValueError):
    pass


class SettingsReference(PromptReference):
    def __init__(self, store, prompt, effort, **kwargs):
        if effort not in ('minimal', 'low'):
            raise ValueError('Effort is outside this frozen comparison')
        super().__init__(store, prompt, **kwargs)
        self.effort = effort
        self.response_events = []

    async def connect(self):
        await super().connect()
        # Both arms perform the same extra update/ack. The inherited connect
        # verifies the unchanged baseline configuration first. No inference.
        expected = session_config()
        expected['reasoning'] = {'effort': self.effort}
        await self.send('session.update', session=expected)
        async with asyncio.timeout(20):
            while True:
                event = await self.receive()
                if event['type'].startswith('response.'):
                    raise ValueError('Unexpected response before explicit generation')
                if event['type'] != 'session.updated':
                    continue
                actual = event['session']
                if actual.get('model') != MODEL:
                    raise ValueError('Wrong realtime model')
                for key in ('instructions', 'max_output_tokens', 'output_modalities',
                            'reasoning', 'truncation', 'tools', 'tool_choice'):
                    if actual.get(key) != expected[key]:
                        raise ValueError('Settings receipt mismatch: '+key)
                audio = actual.get('audio', {})
                if audio.get('input', {}).get('turn_detection') is not None:
                    raise ValueError('Automatic inference must remain disabled')
                if audio.get('output', {}).get('voice') != VOICE:
                    raise ValueError('Unexpected native voice default')
                self.session = copy.deepcopy(actual)
                return

    async def receive(self):
        event = await super().receive()
        if event['type'] in ('response.created', 'response.output_text.delta',
                             'response.output_audio.delta', 'response.done'):
            # Preserve terminal/error-bound evidence even when parent.reply
            # raises before publishing last_result. No credential fields here.
            self.response_events.append(copy.deepcopy(event))
        return event


def budget_preflight(plan, used):
    cfg = plan['configuration']
    required = cfg['required_project_cap_micro_usd']
    if APPROVED_BUDGET_MICRO_USD < required:
        raise BudgetApprovalRequired('Project cap approval required before either paid stage')
    shared_cap = cfg['shared_anchor_micro_usd'] + cfg['maximum_combined_micro_usd']
    if used < cfg['shared_anchor_micro_usd']:
        raise ValueError('Ledger fell below frozen anchor; do not reset or discard reservations')
    if RESERVATION != 1_000_000:
        raise ValueError('Unexpected native reservation policy')
    cap = min(APPROVED_BUDGET_MICRO_USD, shared_cap,
              used + round(plan['limits']['maximum_additional_api_usd']*1e6))
    if used+RESERVATION > cap:
        raise BudgetApprovalRequired('Insufficient room for the unchanged conservative reservation')
    return cap


def require_predecessor(plan, previous):
    required = plan['configuration'].get('predecessor_experiment')
    if not required:
        if previous is not None:
            raise ValueError('Unexpected predecessor')
        return None
    if previous is None:
        raise ValueError('Seal and evaluate organisation stage before effort stage')
    audit(previous)
    record = json.loads((previous/'run.json').read_text())
    if record['experiment_id'] != required or not record['execution_completed']:
        raise ValueError('Wrong or incomplete predecessor')
    if record['decision']['outcome'] not in ('pass', 'fail'):
        raise ValueError('Predecessor needs its frozen labels before continuation')
    return record


async def run(protocol_path, previous=None):
    plan = read_protocol(protocol_path)
    # Fail without creating a run or paid reservation when funding is pending.
    ledger = Store(ROOT/'.tavi/simulation/simulation.sqlite3', must_exist=True)
    try:
        cap = budget_preflight(plan, ledger.used_micro_usd())
        existing = list((ROOT/'.tavi/experiments'/plan['experiment_id']).glob('*/run.json'))
        if existing:
            raise ValueError('This frozen stage already has a run; no automatic retry')
        parent = require_predecessor(plan, previous)
        checks = [audit(p.parent) for p in discover_runs()]
        folder, plan = begin(protocol_path)
        budget = BoundedLedger(ledger, cap-ledger.used_micro_usd(),
                               plan['limits']['maximum_requests'])
        data = json.loads((ROOT/plan['inputs'][0]).read_text())
        arms = plan['configuration']['arms']
        prompts = {name:(ROOT/cfg['prompt']).read_text() for name,cfg in arms.items()}
        result = {'initial_micro_usd':budget.initial, 'rows':[], 'errors':[],
                  'shared_anchor_micro_usd':plan['configuration']['shared_anchor_micro_usd'],
                  'prompt_sha256':{k:hashlib.sha256(v.encode()).hexdigest() for k,v in prompts.items()},
                  'audio':False, 'real_household_history':False, 'predecessor':parent}
        print(json.dumps({'run':str(folder), 'prior_valid_records':len(checks), 'audit':audit(folder)}),flush=True)
        deadline = time.monotonic()+plan['limits']['maximum_wall_seconds']
        def save():
            current = ledger.used_micro_usd()
            result.update(additional_api_usd=(current-budget.initial)/1e6,
                          combined_spent_reserved_usd=(current-result['shared_anchor_micro_usd'])/1e6,
                          total_spent_reserved_usd=current/1e6, requests=budget.calls)
            (folder/'observations.json').write_text(json.dumps(result,indent=2)+'\n')
        try:
            for i,case in enumerate(data['cases']):
                order = ['baseline','candidate'] if i%2==0 else ['candidate','baseline']
                for arm in order:
                    ref = SettingsReference(budget, prompts[arm], arms[arm]['effort'])
                    row = {'case_id':case['id'], 'arm':arm, 'effort':arms[arm]['effort'],
                           'cohort':case['cohort']}
                    result['rows'].append(row)
                    try:
                        remaining = deadline-time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError('Stage deadline')
                        async with asyncio.timeout(min(65, remaining)):
                            started = time.monotonic()
                            await ref.connect()
                            row['connect_ms'] = (time.monotonic()-started)*1000
                            row['session_configuration'] = ref.session
                            reply = await ref.reply(case['task'],case['evidence'],case['id']+'-'+arm)
                            reply['request'] = ref.wire_request
                            row['reply'] = reply
                            if not reply['usage_settled']:
                                raise ValueError('Unknown usage: preserve reservation and stop')
                    finally:
                        await ref.close()
                        row.update(effective_request=ref.wire_request,
                                   response_events=ref.response_events)
                        save()
                    print(json.dumps({'case':case['id'], 'arm':arm, 'effort':row['effort'],
                                      'characters':len(row['reply']['text']),
                                      'additional_api_usd':result['additional_api_usd']}),flush=True)
            packet, regressions, mapping = review_packets(data['cases'], result['rows'],
                                                          plan['configuration']['masking_seed'])
            if regressions:
                raise ValueError('These are paired probes, not candidate-only regressions')
            for entry in packet:
                entry['cohort'] = next(c['cohort'] for c in data['cases'] if c['id']==entry['case_id'])
            (folder/'masked-review.json').write_text(json.dumps(packet,indent=2)+'\n')
            (folder/'arm-map.json').write_text(json.dumps(mapping,indent=2)+'\n')
        except Exception as error:
            result['errors'].append(type(error).__name__+': '+str(error))
        finally:
            save()
        print(json.dumps({'run':str(folder), 'responses':sum('reply' in r for r in result['rows']),
                          'errors':result['errors'], 'additional_api_usd':result['additional_api_usd'],
                          'awaiting':'frozen scoring and critical review before sealing'}),flush=True)
    finally:
        ledger.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--protocol', type=Path, required=True)
    parser.add_argument('--previous', type=Path)
    args = parser.parse_args()
    asyncio.run(run(args.protocol,args.previous))
