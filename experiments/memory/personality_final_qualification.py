"""One fixed-draft qualification; funding approval is required before collection."""
import asyncio
import hashlib
import json

from experiments.memory.personality_trial import run
from tavi.experiment_workflow import ROOT, audit, read_protocol
from tavi.storage import APPROVED_BUDGET_MICRO_USD, Store


def main():
    path = ROOT / 'experiments/memory/personality-qualification-protocol-v4.json'
    plan = read_protocol(path)
    if plan.get('owner_disposition') == 'skipped':
        raise ValueError('Owner skipped this comparison; do not start it')
    cfg = plan['configuration']
    if APPROVED_BUDGET_MICRO_USD < cfg['required_project_cap_micro_usd']:
        raise ValueError('Owner approval of the $31 project cap is required; no request made')
    if list((ROOT / '.tavi/experiments' / plan['experiment_id']).glob('*/run.json')):
        raise ValueError('This qualification already has an attempt; no automatic retry')
    previous = ROOT / cfg['predecessor']
    audit(previous)
    record = json.loads((previous / 'run.json').read_text())
    if not record['execution_completed'] or not record['screen_passed']:
        raise ValueError('The focused explanation/follow-up screen must be sealed pass')
    candidate = ROOT / cfg['prompts']['candidate']
    if hashlib.sha256(candidate.read_bytes()).hexdigest() != cfg['candidate_sha256']:
        raise ValueError('The approved candidate changed')
    ledger = Store(ROOT / '.tavi/simulation/simulation.sqlite3', must_exist=True)
    try:
        if ledger.used_micro_usd() != cfg['ledger_anchor_micro_usd']:
            raise ValueError('Ledger changed; refresh the prospective budget before collection')
    finally:
        ledger.close()
    asyncio.run(run(path))


if __name__ == '__main__':
    main()
