"""One frozen semantic verifier screen; no live guard or automatic rewrite."""
import asyncio
import json
import math
import time
import httpx
from experiments.memory.runtime import ROOT,SSD,require_ssd
from experiments.memory.claim_verifier import verify
from experiments.memory.network_window import probe,clock,qualified
from tavi.storage import Store
from tavi.experiment_workflow import begin,finish,audit

async def run():
    require_ssd();folder,plan=begin(ROOT/'experiments/memory/claim-check-protocol.json',run_root=SSD/'runs/scored')
    print(json.dumps({'run':str(folder),'audit':audit(folder)}),flush=True)
    cases=json.loads((ROOT/'experiments/memory/claim-check-input.json').read_text())['cases']
    ledger=Store(ROOT/'.tavi/simulation/simulation.sqlite3');initial=ledger.used_micro_usd()
    class Envelope:
        calls=0
        def reserve(self,key,amount,cap):
            if self.calls>=28 or ledger.used_micro_usd()+amount>initial+500000:raise ValueError('Verifier experiment limit')
            ledger.reserve(key,amount,cap);self.calls+=1
        def settle(self,key,amount):ledger.settle(key,amount)
    store=Envelope();result={'cases':[],'errors':[]}
    def save():
        result['additional_api_usd']=(ledger.used_micro_usd()-initial)/1e6
        (folder/'observations.json').write_text(json.dumps(result,indent=2)+'\n')
    async def work():
        async with httpx.AsyncClient(timeout=15,trust_env=False) as client:
            for item in cases:
                before=await asyncio.to_thread(probe)
                if not before['ok']:raise RuntimeError('Network preflight failed')
                start=clock();t=time.monotonic();row={'id':item['id'],'expected_accept':item['expected_accept']};result['cases'].append(row)
                try:
                    async with asyncio.timeout(18):r=await verify(client,store,item)
                    row.update(r);row['verification_ms']=(time.monotonic()-t)*1000
                    row['accepted']=r['value']['verdict'] in ('supported','no_factual_claim')
                    row['label_match']=row['accepted']==item['expected_accept']
                except Exception as e:row['error']=type(e).__name__+': '+str(e);row['verification_ms']=(time.monotonic()-t)*1000
                end=clock();after=await asyncio.to_thread(probe)
                row['network']={'before':before,'after':after,'start':start,'end':end,**qualified(before,after,start,end)}
                save();print(json.dumps({'id':row['id'],'match':row.get('label_match'),'ms':round(row['verification_ms']),'error':row.get('error')}),flush=True)
    try:await asyncio.wait_for(work(),600)
    except Exception as e:result['errors'].append(type(e).__name__+': '+str(e))
    finally:save();ledger.close()
    rows=result['cases'];latencies=sorted(r['verification_ms'] for r in rows if 'value' in r)
    metrics={'completed':sum('value' in r for r in rows),'false_accepts':sum(r.get('accepted',False) and not r['expected_accept'] for r in rows),
       'false_blocks':sum(not r.get('accepted',False) and r['expected_accept'] for r in rows),
       'network_qualified':sum(r['network']['qualified'] for r in rows),'errors':len(result['errors'])+sum('error' in r for r in rows),
       'verification_p95_ms':latencies[math.ceil(len(latencies)*.95)-1] if latencies else None,'additional_api_usd':result['additional_api_usd']}
    finish(folder,metrics,artifacts=[folder/'observations.json'],completed=not result['errors'],error='; '.join(result['errors']) or None)
    print(json.dumps({'metrics':metrics,'audit':audit(folder)}),flush=True)

if __name__=='__main__':asyncio.run(run())
