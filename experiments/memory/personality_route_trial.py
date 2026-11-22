"""Eight reused fictional development cases through pinned text Responses.

Different model/transport/reasoning configuration; never a deployment qualifier.
"""
import asyncio
import json
import math
import time
from uuid import uuid4
from tavi.experiment_workflow import ROOT,begin,audit,discover_runs
from tavi.storage import Store,APPROVED_BUDGET_MICRO_USD
from tavi.conversation_providers import runtime_key,MODEL


def request_for(case,prompt):
    content=json.dumps({'task':case['task'],'memory_evidence':case['evidence']},ensure_ascii=False)
    request={'model':MODEL,'instructions':prompt,
             'input':[{'role':'user','content':[{'type':'input_text','text':content}]}],
             'reasoning':{'effort':'none'},'max_output_tokens':768,'store':False,
             'service_tier':'default','tools':[],'stream':False}
    # Byte-as-token input bound plus framing; existing conservative .75/4.5 rates.
    size=len(json.dumps(request,ensure_ascii=False).encode())
    if size>16384 or math.ceil((size+4096)*.75+768*4.5)>50000:
        raise ValueError('Text request exceeds reservation envelope')
    return request


async def run():
    checks=[audit(p.parent) for p in discover_runs()]
    folder,plan=begin(ROOT/'experiments/memory/personality-route-protocol-v1.json')
    print(json.dumps({'run':str(folder),'prior_valid_records':len(checks),'audit':audit(folder)}),flush=True)
    data=json.loads((ROOT/plan['inputs'][0]).read_text());prompt=(ROOT/plan['inputs'][1]).read_text()
    ledger=Store(ROOT/'.tavi/simulation/simulation.sqlite3',must_exist=True);initial=ledger.used_micro_usd()
    result={'initial_micro_usd':initial,'rows':[],'errors':[],'real_audio':False,'reused_development_cases':True}
    from openai import AsyncOpenAI
    client=AsyncOpenAI(api_key=runtime_key(),base_url='https://api.openai.com/v1',max_retries=0,timeout=18)
    responses=client.responses;deadline=time.monotonic()+300
    def save():
        result.update(additional_api_usd=(ledger.used_micro_usd()-initial)/1e6,total_spent_reserved_usd=ledger.used_micro_usd()/1e6)
        (folder/'observations.json').write_text(json.dumps(result,indent=2)+'\n')
    try:
        for case in data['cases']:
            if time.monotonic()>deadline:raise TimeoutError('Diagnostic overall deadline')
            request=request_for(case,prompt);reservation='personality-route:'+uuid4().hex
            ledger.reserve(reservation,50000,min(APPROVED_BUDGET_MICRO_USD,initial+200000))
            row={'case_id':case['id'],'request':request,'reservation':reservation};result['rows'].append(row);save()
            start=time.monotonic()
            async with asyncio.timeout(20):response=await responses.create(**request)
            row['terminal_ms']=(time.monotonic()-start)*1000
            row.update(response=response.model_dump(mode='json'),text=response.output_text,status=response.status,actual_model=response.model)
            usage=response.usage
            if usage is None or any(type(n) is not int or not 0<=n<=128000 for n in [usage.input_tokens,usage.output_tokens]):
                raise ValueError('Usage unknown; keep reservation and stop')
            ledger.settle(reservation,math.ceil(usage.input_tokens*.75+usage.output_tokens*4.5));row['usage_settled']=True
            save()
            if response.model!=MODEL or response.status!='completed' or not response.output_text.strip():
                raise ValueError('Unqualified model or incomplete text response')
            print(json.dumps({'case':case['id'],'characters':len(response.output_text),'additional_api_usd':result['additional_api_usd']}),flush=True)
    except Exception as exc:
        result['errors'].append(type(exc).__name__+': '+str(exc));print(json.dumps({'error_type':type(exc).__name__}),flush=True)
    finally:
        await client.close();save();ledger.close()
    print(json.dumps({'run':str(folder),'collected':len(result['rows']),'errors':len(result['errors']),'additional_api_usd':result['additional_api_usd'],'awaiting':'reused development labels only; no deployment decision'}),flush=True)


if __name__=='__main__':asyncio.run(run())
