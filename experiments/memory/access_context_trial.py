"""One paired reused-context diagnostic, no retrieval or prompt/engine sweep."""
import asyncio
import io
import json
from pathlib import Path
import time
import unittest
from experiments.memory.runtime import ROOT,SSD,require_ssd
from experiments.memory.access_evidence import with_access_decision
from experiments.memory.native_text import NativeTextReference
from tavi.storage import Store
from tavi.experiment_workflow import begin,audit


async def run():
    require_ssd();folder,plan=begin(ROOT/'experiments/memory/access-context-protocol-v1.json',run_root=SSD/'runs/scored')
    print(json.dumps({'run':str(folder),'audit':audit(folder)}),flush=True)
    cfg=json.loads((ROOT/'experiments/memory/access-context-input-v1.json').read_text())
    saved=json.loads(Path(cfg['source_observations']).read_text());by_id={r['id']:r for r in saved['cases']}
    stream=io.StringIO();tests=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromName('tests.test_access_evidence'))
    (folder/'controls.txt').write_text(stream.getvalue())
    ledger=Store(ROOT/'.tavi/simulation/simulation.sqlite3');initial=ledger.used_micro_usd();ref=None
    result={'rows':[],'errors':[],'controlled_checks_passed':tests.testsRun-len(tests.failures)-len(tests.errors),'test_failures':len(tests.failures)+len(tests.errors),
        'initial_spent_reserved_usd':initial/1e6,'new_retrieval_or_extraction':False,'voice':False,'oracle_read_by_collector':False}
    deadline=time.monotonic()+plan['limits']['maximum_wall_seconds']
    class Budget:
        calls=0
        def reserve(self,key,amount,cap):
            if self.calls>=8:raise ValueError('Access comparison reply limit')
            ledger.reserve(key,amount,min(cap,initial+2_000_000));self.calls+=1
        def settle(self,key,amount):ledger.settle(key,amount)
    budget=Budget()
    def save():
        result.update(additional_api_usd=(ledger.used_micro_usd()-initial)/1e6,total_spent_reserved_usd=ledger.used_micro_usd()/1e6,reply_requests=budget.calls)
        (folder/'observations.json').write_text(json.dumps(result,indent=2)+'\n')
    try:
        if result['test_failures']:raise ValueError('Permission metadata controls failed; no inference')
        for index,qid in enumerate(cfg['case_ids']):
            original=by_id[qid];task=original['task'];baseline=original['boundary']['evidence']
            candidate=with_access_decision(task,baseline,saved['sources'])['evidence']
            if candidate['facts']!=baseline['facts'] or candidate['source_headers']!=baseline['source_headers']:
                raise ValueError('Permission metadata changed source facts')
            for arm in (['baseline','candidate'] if index%2==0 else ['candidate','baseline']):
                remaining=deadline-time.monotonic()
                if remaining<=0:raise TimeoutError('Access comparison overall deadline')
                evidence=baseline if arm=='baseline' else candidate
                row={'id':qid,'arm':arm,'task':task,'evidence':evidence};result['rows'].append(row)
                ref=NativeTextReference(budget)
                try:
                    async with asyncio.timeout(min(60,remaining)):
                        await ref.connect();row['reply']=await ref.reply(task,evidence,qid+'-'+arm)
                finally:await ref.close();ref=None
                save();print(json.dumps({'id':qid,'arm':arm,'reply':row['reply']['text']}),flush=True)
    except Exception as error:result['errors'].append(type(error).__name__+': '+str(error))
    finally:
        if ref:await ref.close()
        save();ledger.close()
    print(json.dumps({'run':str(folder),'errors':result['errors'],'cost':result['additional_api_usd'],'awaiting':'Explicit paired review; no automatic adoption'}),flush=True)


if __name__=='__main__':asyncio.run(run())
