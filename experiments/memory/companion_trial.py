"""Frozen fictional companion comparison; no promotion or automated quality judge."""
import json,os,signal,time
from experiments.memory.runtime import ROOT,SSD,CAPACITY_MODEL,require_ssd
from experiments.memory.pilot import Process
from experiments.memory.context_envelope import pack
from experiments.memory.companion_contract import MISSION,task_payload
from tavi.experiment_workflow import begin,audit


def run():
    import httpx,tiktoken
    require_ssd();os.environ['TIKTOKEN_CACHE_DIR']=str(SSD/'models/tiktoken')
    folder,protocol=begin(ROOT/'experiments/memory/companion-protocol-v1.json',run_root=SSD/'runs/scored')
    print(json.dumps({'run':str(folder),'audit':audit(folder)}),flush=True)
    broker=json.loads((SSD/'private-config/broker.json').read_text())
    fixture=json.loads((ROOT/'experiments/memory/companion-input-v1.json').read_text())
    cases=json.loads((ROOT/'experiments/memory/companion-cases-v1.json').read_text())
    encoding=tiktoken.get_encoding('o200k_base');workers={};logs=folder/'logs';logs.mkdir()
    obs={'ingests':[],'cases':[],'errors':[],'answer_calls':[]}
    def save():(folder/'observations.json').write_text(json.dumps(obs,indent=2))
    def send(engine,request):
        r=workers[engine].send(request,timeout=420)
        if not r['ok']:raise RuntimeError(engine+': '+r['error'])
        return r['result']
    def answer(task,evidence):
        r=httpx.post(broker['base_url']+'/evaluator/v1/chat/completions',headers={'Authorization':'Bearer '+broker['token']},
            json={'model':CAPACITY_MODEL,'messages':[{'role':'system','content':MISSION},
                 {'role':'user','content':json.dumps({'task':task,'memory_evidence':evidence})}],
                 'temperature':0,'store':False,'max_completion_tokens':512,
                 'response_format':{'type':'json_schema','json_schema':{'name':'companion_reply','strict':True,
                     'schema':{'type':'object','properties':{'text':{'type':'string'}},'required':['text'],'additionalProperties':False}}}},timeout=100)
        r.raise_for_status();v=r.json();obs['answer_calls'].append(v);save()
        c=v['choices'][0]
        if v.get('model')!=CAPACITY_MODEL or c['finish_reason']!='stop' or c['message'].get('refusal'):
            raise ValueError('Incomplete or unexpected common reply model')
        return json.loads(c['message']['content'])['text']
    def expired(*args):raise TimeoutError('Companion trial wall limit')
    signal.signal(signal.SIGALRM,expired);signal.alarm(protocol['limits']['maximum_wall_seconds'])
    try:
        for engine in ['hindsight','mem0']:
            directory=SSD/'databases'/folder.parent.name/(folder.name+'-'+engine)
            workers[engine]=Process(engine,directory,logs,'companion_worker.py')
            send(engine,{'op':'initialize'})
            for source in fixture['episodes']:
                start=time.monotonic();v=send(engine,{'op':'ingest','episode':source,'people':fixture['people']})
                obs['ingests'].append({'engine':engine,'source':source['id'],'result':v,'elapsed_ms':(time.monotonic()-start)*1000});save()
                print(json.dumps({'engine':engine,'source':source['id']}),flush=True)
        arms=['no_memory','hindsight_recall','mem0','hindsight_reflect']
        for index,case in enumerate(cases):
            # Rotate complete pipeline order, but retain shared native ingests.
            for arm in arms[index%4:]+arms[:index%4]:
                started=time.monotonic();task=task_payload(case,fixture['people'],fixture['catalogue'])
                record={'case_id':case['id'],'arm':arm,'task':task}
                known=case['asker'] in fixture['people']
                if arm=='hindsight_reflect' and known:
                    result=send('hindsight',{'op':'reflect','question':case,'people':fixture['people'],'task':task})
                    record['reflection']=result;record['text']=result['native']['text']
                else:
                    evidence={}
                    if arm!='no_memory' and known:
                        engine='hindsight' if arm=='hindsight_recall' else arm
                        retrieval=send(engine,{'op':'query','question':case,'people':fixture['people']})
                        envelope=pack(engine,retrieval['native_context'],fixture['episodes'],case['audience_ids'],encoding)
                        evidence=json.loads(envelope['context']);record.update(retrieval=retrieval,envelope=envelope)
                    record['text']=answer(task,evidence)
                    if arm=='hindsight_reflect':record['unknown_identity_no_memory_fallback']=True
                record['elapsed_ms']=(time.monotonic()-started)*1000;obs['cases'].append(record);save()
                print(json.dumps({'case':case['id'],'arm':arm,'complete':True}),flush=True)
    except Exception as exc:
        obs['errors'].append(type(exc).__name__+': '+str(exc));save()
    finally:
        signal.alarm(0)
        # Disable first, so shutdown cannot initiate a paid retry or background job.
        response=httpx.post(broker['base_url']+'/control/disable-paid',headers={'Authorization':'Bearer '+broker['token']},timeout=100)
        response.raise_for_status();(folder/'calls-final.json').write_text(json.dumps(response.json()['calls'],indent=2))
        for worker in workers.values():worker.stop()
        save()
    print(json.dumps({'awaiting_explicit_review':str(folder),'errors':obs['errors']}),flush=True)


if __name__=='__main__':run()
