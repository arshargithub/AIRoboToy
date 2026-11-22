"""Single prospective text-only persona comparison; never imports real chat data."""
import argparse
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import random
import time

from experiments.memory.native_text import NativeTextReference
from tavi.experiment_workflow import ROOT, begin, audit, discover_runs
from tavi.storage import Store


class PromptReference(NativeTextReference):
    """Experiment-only override. Production MISSION stays untouched until sealed."""
    def __init__(self, store, prompt, **kwargs):
        super().__init__(store, **kwargs)
        self.prompt = prompt
        self.wire_request = None

    async def send(self, kind, **fields):
        if kind == 'response.create':
            fields = copy.deepcopy(fields)
            fields['response']['instructions'] = self.prompt
            self.wire_request = copy.deepcopy(fields['response'])
        await super().send(kind, **fields)


class BoundedLedger:
    def __init__(self, ledger, maximum, calls):
        self.ledger = ledger
        self.initial = ledger.used_micro_usd()
        self.cap = self.initial + maximum
        self.maximum_calls = calls
        self.calls = 0

    def reserve(self, key, amount, cap):
        if self.calls >= self.maximum_calls:
            raise ValueError('Prospective request bound exhausted')
        self.ledger.reserve(key, amount, min(cap, self.cap))
        self.calls += 1

    def settle(self, key, amount):
        self.ledger.settle(key, amount)


def review_packets(cases, rows, seed):
    """Separate development regressions from paired fresh evidence."""
    packet=[];regressions=[];mapping={};rng=random.Random(seed)
    for case in cases:
        collected=[r for r in rows if r['case_id']==case['id']]
        if case.get('cohort')=='regression':
            if len(collected)!=1 or collected[0]['arm']!='candidate':
                raise ValueError('Regression must have exactly one candidate response')
            regressions.append({'case_id':case['id'],'required':case['required'],
                                'text':collected[0]['reply']['text']})
            continue
        if len(collected)!=2 or {r['arm'] for r in collected}!={'baseline','candidate'}:
            raise ValueError('Fresh pair must have both arms exactly once')
        rng.shuffle(collected)
        packet.append({'case_id':case['id'],'question':case['task']['question'],
                       'required':case['required'],'style_case':case['style_case'],
                       'left':collected[0]['reply']['text'],'right':collected[1]['reply']['text']})
        mapping[case['id']]={'left':collected[0]['arm'],'right':collected[1]['arm']}
    return packet,regressions,mapping


async def run(protocol_path=None):
    # A missing external evidence drive must fail the complete audit, not vanish.
    checks = [audit(p.parent) for p in discover_runs()]
    folder, plan = begin(protocol_path or ROOT/'experiments/memory/personality-protocol-v1.json')
    print(json.dumps({'run':str(folder), 'prior_valid_records':len(checks), 'audit':audit(folder)}), flush=True)
    data = json.loads((ROOT/plan['inputs'][0]).read_text())
    prompts = {k:(ROOT/v).read_text() for k,v in plan['configuration']['prompts'].items()}
    ledger = Store(ROOT/'.tavi/simulation/simulation.sqlite3', must_exist=True)
    budget = BoundedLedger(ledger, round(plan['limits']['maximum_additional_api_usd']*1e6),
                           plan['limits']['maximum_requests'])
    result = {'initial_micro_usd':budget.initial, 'rows':[], 'errors':[],
              'session_configuration':None, 'prompt_sha256':{k:hashlib.sha256(v.encode()).hexdigest() for k,v in prompts.items()},
              'audio':False,'real_household_history':False}
    deadline = time.monotonic()+plan['limits']['maximum_wall_seconds']
    def save():
        result.update(additional_api_usd=(ledger.used_micro_usd()-budget.initial)/1e6,
                      total_spent_reserved_usd=ledger.used_micro_usd()/1e6,requests=budget.calls)
        (folder/'observations.json').write_text(json.dumps(result,indent=2)+'\n')
    try:
        for i,case in enumerate(data['cases']):
            arms = list(case.get('arms',['baseline','candidate']))
            if i%2:arms.reverse()
            for arm in arms:
                client = PromptReference(budget,prompts[arm])
                row = {'case_id':case['id'], 'arm':arm,'cohort':case.get('cohort','fresh')}
                result['rows'].append(row)
                try:
                    async with asyncio.timeout(min(60,max(0.01,deadline-time.monotonic()))):
                        await client.connect()
                        result['session_configuration'] = client.session
                        row['session_configuration'] = client.session
                        reply = await client.reply(case['task'],case['evidence'],case['id']+'-'+arm)
                        # NativeTextReference records pre-override options; report actual wire.
                        reply['request'] = client.wire_request
                        row['reply'] = reply
                        if not reply['usage_settled']:
                            raise ValueError('Unknown usage: reservation preserved; stop')
                finally:
                    await client.close()
                    if client.wire_request is not None:
                        row['effective_request'] = client.wire_request
                    save()
                print(json.dumps({'case':case['id'],'arm':arm,'characters':len(row['reply']['text']),
                                  'additional_api_usd':result['additional_api_usd']}),flush=True)
        packet,regressions,mapping=review_packets(data['cases'],result['rows'],
                                                plan['configuration'].get('masking_seed',73017))
        (folder/'masked-review.json').write_text(json.dumps(packet,indent=2)+'\n')
        (folder/'regression-review.json').write_text(json.dumps(regressions,indent=2)+'\n')
        (folder/'arm-map.json').write_text(json.dumps(mapping,indent=2)+'\n')
    except Exception as exc:
        result['errors'].append(type(exc).__name__+': '+str(exc))
        print(json.dumps({'error':result['errors'][-1]}),flush=True)
    finally:
        save();ledger.close()
    print(json.dumps({'run':str(folder),'completed':sum('reply' in r for r in result['rows']),
                      'errors':result['errors'],'additional_api_usd':result['additional_api_usd'],
                      'awaiting':'frozen rubric labels and critical review before finish'}),flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--protocol',type=Path)
    asyncio.run(run(parser.parse_args().protocol))
