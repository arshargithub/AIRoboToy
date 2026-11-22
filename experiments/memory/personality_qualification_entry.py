"""Funding guard for the proposed full development regression; no auto adoption."""
import asyncio
from tavi.storage import APPROVED_BUDGET_MICRO_USD
from tavi.experiment_workflow import ROOT,read_protocol
from experiments.memory.personality_trial import run


def main():
    path=ROOT/'experiments/memory/personality-regression-protocol-v3.json'
    plan=read_protocol(path)
    if APPROVED_BUDGET_MICRO_USD<plan['configuration']['required_project_cap_micro_usd']:
        raise ValueError('Full regression is prepared but requires explicit project-cap28USDapproval')
    if list((ROOT/'.tavi/experiments'/plan['experiment_id']).glob('*/run.json')):
        raise ValueError('The prepared full regression already has an attempt')
    asyncio.run(run(path))


if __name__=='__main__':main()
