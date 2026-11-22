"""One bounded current-path fictional diagnostic; no microphone or voice synthesis.

Collection deliberately does not read the evaluator oracle or choose new prompts.
Extraction is disabled before the final reply phase, bounding combined spending.
"""
import asyncio
import json
import os
from pathlib import Path
import time
from experiments.memory.runtime import ROOT,SSD,require_ssd
from experiments.memory.build_reliability_cases import public_question
from experiments.memory.learning_gateway import LearningGateway
from experiments.memory.pilot import Process
from experiments.memory.context_envelope import pack
from experiments.memory.reply_boundary import qualify_context
from experiments.memory.native_text import NativeTextReference
from tavi.conversation import LOCAL_REPLIES
from tavi.listen_only import listen_only
from tavi.storage import Store
from tavi.experiment_workflow import begin,audit


async def run():
    require_ssd();folder,plan=begin(ROOT/'experiments/memory/reliability-protocol-v1.json',run_root=SSD/'runs/scored')
    print(json.dumps({'run':str(folder),'audit':audit(folder)}),flush=True)
    data=json.loads((ROOT/'experiments/memory/reliability-input-v1.json').read_text())
    os.environ['TIKTOKEN_CACHE_DIR']=str(SSD/'models/tiktoken');import tiktoken
    encoding=tiktoken.get_encoding('o200k_base');logs=folder/'logs';logs.mkdir()
    ledger=Store(ROOT/'.tavi/simulation/simulation.sqlite3');initial=ledger.used_micro_usd()
    deadline=time.monotonic()+plan['limits']['maximum_wall_seconds'];worker=None;gateway=None;ref=None;sources=[]
    result={'ingests':[],'cases':[],'errors':[],'initial_spent_reserved_usd':initial/1e6,
        'audio':False,'microphone':False,'native_directory':str(folder/'native'),'oracle_read_by_collector':False}
    extraction_closed=False
    class Budget:
        calls=0
        def reserve(self,key,amount,cap):
            if self.calls>=23:raise ValueError('Reply request limit')
            # Exactly one early question while extractor can spend at most$1.
            # After extraction is disabled there can be no background paid
            # growth, so all later replies use the shared$3run ceiling.
            if not extraction_closed and self.calls:raise ValueError('Only one early reply allowed')
            ledger.reserve(key,amount,min(cap,initial+(3_000_000 if extraction_closed else 2_000_000)))
            self.calls+=1
        def settle(self,key,amount):ledger.settle(key,amount)
    budget=Budget()
    def remaining():
        value=deadline-time.monotonic()
        if value<=0:raise TimeoutError('Reliability diagnostic overall deadline')
        return value
    def save():
        result.update(sources=sources,reply_requests=budget.calls,extraction_closed=extraction_closed,
            additional_api_usd=(ledger.used_micro_usd()-initial)/1e6,total_spent_reserved_usd=ledger.used_micro_usd()/1e6)
        (folder/'observations.json').write_text(json.dumps(result,indent=2)+'\n')
    def send(request):
        out=worker.send(request,timeout=min(420,remaining()))
        if not out['ok']:raise RuntimeError(out['error'])
        return out['result']
    async def query(case):
        nonlocal ref
        public=public_question(case);row={'id':case['id'],'question':case};result['cases'].append(row)
        if listen_only(public['text']):
            row.update(route='existing_local_listen_only',reply={'text':LOCAL_REPLIES['listen'],'status':'completed'},retrieval_skipped=True)
            save();return
        before=time.monotonic();native=send({'op':'query','question':public,'people':data['people']})
        packed=pack('hindsight',native['native_context'],sources,public['audience_ids'],encoding)
        task={'people':data['people'],'actual_speaker_id':public['asker'],'audience_ids':public['audience_ids'],
            'conversation_at':public['at'],'question':public['text'],'catalogue':public['catalogue'],'recent_conversation':[]}
        boundary=qualify_context(task,json.loads(packed['context']),sources)
        row.update(route='native_text',task=task,native=native,packed=packed,boundary=boundary,
            context_ready_ms=(time.monotonic()-before)*1000)
        ref=NativeTextReference(budget)
        try:
            async with asyncio.timeout(min(60,remaining())):
                await ref.connect();row['reply']=await ref.reply(task,boundary['evidence'],case['id'])
        finally:await ref.close();ref=None
        save();print(json.dumps({'id':case['id'],'facts':len(boundary['evidence']['facts']),'reply':row['reply']['text']}),flush=True)
    try:
        gateway=LearningGateway(folder);await asyncio.to_thread(gateway.start)
        worker=Process('hindsight',folder/'native',logs,'learning_worker.py');send({'op':'initialize'})
        for source in data['episodes']:
            before=time.monotonic();native=send({'op':'ingest','episode':source,'people':data['people']})
            sources.append(source);result['ingests'].append({'id':source['id'],'native':native,'elapsed_ms':(time.monotonic()-before)*1000});save()
            # Final phase must be unable to spend on extraction, including
            # residual jobs. Free local embedding endpoints remain available.
            if source['id']==data['episodes'][-1]['id']:
                result['gateway_disabled']=await asyncio.to_thread(gateway.close);extraction_closed=True;save()
            for case in data['cases']:
                if case['after']==source['id']:await query(case)
    except Exception as error:
        result['errors'].append(type(error).__name__+': '+str(error));print(json.dumps({'error_type':type(error).__name__}),flush=True)
    finally:
        if ref:await ref.close()
        if worker:worker.stop()
        if gateway and not extraction_closed:result['gateway_disabled']=await asyncio.to_thread(gateway.close)
        save();ledger.close()
    print(json.dumps({'run':str(folder),'cases':len(result['cases']),'errors':result['errors'],
        'additional_api_usd':result['additional_api_usd'],'awaiting':'Explicit source-paired review before finish'}),flush=True)


if __name__=='__main__':asyncio.run(run())
