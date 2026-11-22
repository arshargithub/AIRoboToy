"""Resume only unstarted responses after a sealed pre-inference credit block."""
import asyncio
import copy
import hashlib
import json
import time
from pathlib import Path
from experiments.memory.personality_continuation import remaining_requests
from experiments.memory.personality_trial import PromptReference,BoundedLedger,review_packets
from tavi.experiment_workflow import ROOT,read_protocol,begin,audit,discover_runs
from tavi.storage import Store,APPROVED_BUDGET_MICRO_USD


def verified_parent(plan):
    folder=ROOT/plan['configuration']['parent_folder'];audit(folder)
    record=json.loads((folder/'run.json').read_text())
    manifest=json.loads((folder/'continuation-manifest.json').read_text())
    parent=json.loads((folder/'observations.json').read_text())
    if record['state']!='finished' or record['execution_completed'] or 'credit_balance_exhausted' not in record.get('error',''):
        raise ValueError('Parent is not the sealed pre-inference credit interruption')
    for name,sha in {**manifest['source_sha256'],**manifest['input_sha256']}.items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=sha:
            raise ValueError('Original source/input changed: '+name)
    data=json.loads((ROOT/plan['inputs'][0]).read_text())
    pending=remaining_requests(data['cases'],parent['rows'])
    expected=[{'case_id':r['case_id'],'arm':r['arm']} for r in manifest['remaining_in_original_order']]
    if pending!=expected or len(pending)!=plan['limits']['maximum_requests']:
        raise ValueError('Continuation does not match frozen remaining requests')
    completed={(r['case_id'],r['arm']):r for r in parent['rows'] if r.get('reply',{}).get('status')=='completed'}
    for info in manifest['completed_keys']:
        row=completed[info['case_id'],info['arm']]
        if hashlib.sha256(json.dumps(row,sort_keys=True).encode()).hexdigest()!=info['row_sha256']:
            raise ValueError('Completed response changed')
    if len(completed)!=27 or parent['requests']!=27:
        raise ValueError('Unexpected parent request count')
    return parent,manifest,data,pending


def combine_observations(parent,resumed,cases):
    old=[copy.deepcopy(r) for r in parent['rows'] if r.get('reply',{}).get('status')=='completed']
    new=copy.deepcopy(resumed['rows'])
    for r in old:r['collection_segment']='before_credit_restoration'
    for r in new:r['collection_segment']='after_credit_restoration'
    allrows=old+new
    if remaining_requests(cases,allrows):raise ValueError('Merged matrix is incomplete')
    return {'rows':allrows,'errors':list(resumed['errors']),
            'recovered_parent_errors':list(parent['errors']),
            'interruptions':[{'kind':'credit_balance_exhausted','before_response_index':28}],
            'additional_api_usd':resumed['additional_api_usd'],
            'full_comparison_additional_api_usd':resumed['full_comparison_additional_api_usd'],
            'total_spent_reserved_usd':resumed['total_spent_reserved_usd']}


async def run():
    path=ROOT/'experiments/memory/personality-continuation-protocol-v1.json';plan=read_protocol(path)
    if list((ROOT/'.tavi/experiments'/plan['experiment_id']).glob('*/run.json')):
        raise ValueError('Continuation already attempted; no automatic retry')
    parent,manifest,data,pending=verified_parent(plan)
    ledger=Store(ROOT/'.tavi/simulation/simulation.sqlite3',must_exist=True)
    try:
        current=ledger.used_micro_usd()
        if current<round(parent['total_spent_reserved_usd']*1e6):raise ValueError('Spending ledger changed backwards')
        combined_cap=manifest['original_initial_micro_usd']+manifest['original_max_additional_micro_usd']
        cap=min(APPROVED_BUDGET_MICRO_USD,combined_cap)
        if cap-current<1000000:raise ValueError('Insufficient unchanged reservation headroom')
        audits=[audit(f.parent) for f in discover_runs()]
        folder,plan=begin(path);budget=BoundedLedger(ledger,cap-current,len(pending))
        prompts={arm:(ROOT/p).read_text() for arm,p in plan['configuration']['prompts'].items()}
        result={'rows':[],'errors':[],'parent_folder':plan['configuration']['parent_folder'],
                'prior_completed':27,'initial_micro_usd':current,'original_initial_micro_usd':manifest['original_initial_micro_usd'],
                'audio':False,'real_household_history':False}
        print(json.dumps({'run':str(folder),'prior_valid_records':len(audits),'audit':audit(folder),'new_requests_only':len(pending)}),flush=True)
        deadline=time.monotonic()+plan['limits']['maximum_wall_seconds']
        def save():
            used=ledger.used_micro_usd()
            result.update(requests=budget.calls,additional_api_usd=(used-current)/1e6,
              full_comparison_additional_api_usd=(used-manifest['original_initial_micro_usd'])/1e6,total_spent_reserved_usd=used/1e6)
            (folder/'observations.json').write_text(json.dumps(result,indent=2)+'\n')
        try:
            for request in pending:
                case=next(c for c in data['cases'] if c['id']==request['case_id']);arm=request['arm']
                ref=PromptReference(budget,prompts[arm]);row={'case_id':case['id'],'arm':arm,'cohort':case['cohort']};result['rows'].append(row)
                try:
                    remaining=deadline-time.monotonic()
                    if remaining<=0:raise TimeoutError('Continuation deadline')
                    async with asyncio.timeout(min(60,remaining)):
                        await ref.connect();row['session_configuration']=ref.session
                        reply=await ref.reply(case['task'],case['evidence'],case['id']+'-'+arm)
                        reply['request']=ref.wire_request;row['reply']=reply
                        if not reply['usage_settled']:raise ValueError('Unknown usage: preserve reservation and stop')
                finally:
                    await ref.close();row['effective_request']=ref.wire_request;save()
                print(json.dumps({'case':case['id'],'arm':arm,'characters':len(reply['text']),
                                  'continuation_api_usd':result['additional_api_usd']}),flush=True)
            merged=combine_observations(parent,result,data['cases'])
            packet,regressions,mapping=review_packets(data['cases'],merged['rows'],plan['configuration']['masking_seed'])
            for name,value in [('combined-observations.json',merged),('masked-review.json',packet),('regression-review.json',regressions),('arm-map.json',mapping)]:
                (folder/name).write_text(json.dumps(value,indent=2)+'\n')
        except Exception as e:
            result['errors'].append(type(e).__name__+': '+str(e))
        finally:save()
        print(json.dumps({'run':str(folder),'new_responses':sum('reply' in r for r in result['rows']),
                          'errors':result['errors'],'additional_api_usd':result['additional_api_usd'],
                          'full_comparison_api_usd':result['full_comparison_additional_api_usd'],
                          'awaiting':'Merged45response masked review; original parent remains sealed error'}),flush=True)
    finally:ledger.close()


if __name__=='__main__':asyncio.run(run())
