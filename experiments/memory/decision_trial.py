"""Fresh combined native recall/single-call decision trial, not a live adapter."""
import json,os,random,signal,time
from experiments.memory.runtime import ROOT,SSD,CAPACITY_MODEL,require_ssd
from experiments.memory.pilot import Process
from experiments.memory.context_envelope import pack
from experiments.memory.companion_contract import MISSION
from experiments.memory.decision_contract import DECISION_MISSION,SCHEMA,snapshot,validate
from tavi.experiment_workflow import begin,audit


def run():
    import httpx,tiktoken
    require_ssd();os.environ['TIKTOKEN_CACHE_DIR']=str(SSD/'models/tiktoken')
    p,plan=begin(ROOT/'experiments/memory/decision-protocol-v1.json',run_root=SSD/'runs/scored')
    print(json.dumps({'run':str(p),'audit':audit(p)}),flush=True)
    fixture=json.loads((ROOT/'experiments/memory/decision-input-v1.json').read_text());enc=tiktoken.get_encoding('o200k_base')
    broker=json.loads((SSD/'private-config/broker.json').read_text());headers={'Authorization':'Bearer '+broker['token']}
    o={'ingests':[],'retrievals':[],'cases':[],'errors':[]};logs=p/'logs';logs.mkdir();worker=None
    def save():(p/'observations.json').write_text(json.dumps(o,indent=2))
    def send(request):
        r=worker.send(request,timeout=420)
        if not r['ok']:raise RuntimeError(r['error'])
        return r['result']
    def expired(*args):raise TimeoutError('Decision trial wall bound')
    signal.signal(signal.SIGALRM,expired);signal.alarm(plan['limits']['maximum_wall_seconds'])
    try:
        directory=SSD/'databases'/p.parent.name/p.name;worker=Process('hindsight',directory,logs,'guarded_worker.py');send({'op':'initialize'})
        for source in fixture['episodes']:
            result=send({'op':'ingest','episode':source,'people':fixture['people']})
            o['ingests'].append({'id':source['id'],'result':result});save();print(json.dumps({'source':source['id']}),flush=True)
        worker.stop();worker=Process('hindsight',directory,logs,'guarded_worker.py');send({'op':'initialize'})
        tasks=[]
        for case in fixture['cases']:
            started=time.monotonic();retrieval=send({'op':'query','question':case,'people':fixture['people']})
            envelope=pack('hindsight',retrieval['native_context'],fixture['episodes'],case['audience_ids'],enc)
            evidence=json.loads(envelope['context']);elapsed=(time.monotonic()-started)*1000
            task={'actual_speaker_id':case['asker'],'people':fixture['people'],'audience_ids':case['audience_ids'],
                  'conversation_at':case['at'],'question':case['text'],'recent_conversation':[],'catalogue':case['catalogue']}
            o['retrievals'].append({'id':case['id'],'native':retrieval,'envelope':envelope,'elapsed_ms':elapsed});save()
            tasks.append({'id':case['id'],'task':task,'memory_evidence':evidence,'oracle':case['oracle'],'origin':case['origin'],'context_ms':elapsed})
        for case in fixture['regressions']:tasks.append({**case,'context_ms':0})
        for index,case in enumerate(tasks):
            task=case['task'];evidence=case['memory_evidence'];bound=snapshot(task,evidence)
            for arm in (['text_control','decision_candidate'] if index%2==0 else ['decision_candidate','text_control']):
                schema=SCHEMA if arm=='decision_candidate' else {'type':'object','properties':{'text':{'type':'string'}},'required':['text'],'additionalProperties':False}
                start=time.monotonic()
                response=httpx.post(broker['base_url']+'/evaluator/v1/chat/completions',headers=headers,json={
                    'model':CAPACITY_MODEL,'store':False,'reasoning_effort':'low','max_completion_tokens':2048,
                    'messages':[{'role':'system','content':DECISION_MISSION if arm=='decision_candidate' else MISSION},
                                {'role':'user','content':json.dumps({'task':task,'memory_evidence':evidence})}],
                    'response_format':{'type':'json_schema','json_schema':{'name':'memory_reply','strict':True,'schema':schema}}},timeout=100)
                response.raise_for_status();raw=response.json();choice=raw['choices'][0]
                if raw.get('model')!=CAPACITY_MODEL or choice['finish_reason']!='stop' or choice['message'].get('refusal'):
                    raise ValueError('Incomplete or unexpected response model')
                value=json.loads(choice['message']['content']);validation=None
                if arm=='decision_candidate':
                    try:validation=validate(value,task,evidence,issued_snapshot=bound,current_snapshot=snapshot(task,evidence))
                    except (ValueError,TypeError,KeyError) as exc:validation={'blocked':True,'reason':str(exc),'semantic_grounding_verified':False}
                row={'case_id':case['id'],'arm':arm,'task':task,'memory_evidence':evidence,'oracle':case['oracle'],'origin':case['origin'],
                     'value':value,'text':value['text'],'validation':validation,'response':raw,'request_snapshot':bound,
                     'response_ms':(time.monotonic()-start)*1000,'context_ms':case['context_ms']}
                row['pipeline_ms']=row['response_ms']+row['context_ms'];o['cases'].append(row);save()
            print(json.dumps({'case':case['id'],'paired_complete':True}),flush=True)
    except Exception as exc:o['errors'].append(type(exc).__name__+': '+str(exc));save()
    finally:
        signal.alarm(0)
        r=httpx.post(broker['base_url']+'/control/disable-paid',headers=headers,timeout=100);r.raise_for_status()
        (p/'calls-final.json').write_text(json.dumps(r.json()['calls'],indent=2))
        if worker:worker.stop()
        save()
    deck=[];mapping={}
    for cid in dict.fromkeys(r['case_id'] for r in o['cases']):
        rows=[r for r in o['cases'] if r['case_id']==cid];random.SystemRandom().shuffle(rows)
        for i,row in enumerate(rows):
            key=cid+'-'+chr(65+i);mapping[key]=row['arm']
            # First review only visible replies with arm names/receipts hidden;
            # candidate receipt semantics must then be reviewed separately.
            deck.append({k:row[k] for k in ['task','memory_evidence','oracle','origin','text']}|{'label':key})
    (p/'review-deck.json').write_text(json.dumps(deck,indent=2));(p/'review-mapping.json').write_text(json.dumps(mapping,indent=2))
    print(json.dumps({'awaiting_review':str(p),'errors':o['errors']}),flush=True)

if __name__=='__main__':run()
