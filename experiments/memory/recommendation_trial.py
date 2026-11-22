"""Paired single-call response screen; labels require explicit source review."""
import json,random,signal,time
from experiments.memory.runtime import ROOT,SSD,CAPACITY_MODEL,require_ssd
from experiments.memory.companion_contract import MISSION
from experiments.memory.recommendation_contract import RECOMMENDATION_MISSION
from tavi.experiment_workflow import begin,audit


def run():
    import httpx
    require_ssd();p,plan=begin(ROOT/'experiments/memory/recommendation-protocol-v1.json',run_root=SSD/'runs/scored')
    print(json.dumps({'run':str(p),'audit':audit(p)}),flush=True)
    broker=json.loads((SSD/'private-config/broker.json').read_text());fixtures=json.loads((ROOT/'experiments/memory/recommendation-cases-v1.json').read_text())
    obs={'cases':[],'errors':[]};headers={'Authorization':'Bearer '+broker['token']}
    def save():(p/'observations.json').write_text(json.dumps(obs,indent=2))
    def expired(*args):raise TimeoutError('Recommendation trial wall limit')
    signal.signal(signal.SIGALRM,expired);signal.alarm(plan['limits']['maximum_wall_seconds'])
    try:
        for index,case in enumerate(fixtures):
            for arm in (['control','candidate'] if index%2==0 else ['candidate','control']):
                start=time.monotonic()
                response=httpx.post(broker['base_url']+'/evaluator/v1/chat/completions',headers=headers,json={
                    'model':CAPACITY_MODEL,'store':False,'temperature':0,'max_completion_tokens':512,
                    'messages':[{'role':'system','content':MISSION if arm=='control' else RECOMMENDATION_MISSION},
                                {'role':'user','content':json.dumps({'task':case['task'],'memory_evidence':case['memory_evidence']})}],
                    'response_format':{'type':'json_schema','json_schema':{'name':'companion_reply','strict':True,
                        'schema':{'type':'object','properties':{'text':{'type':'string'}},'required':['text'],'additionalProperties':False}}}},timeout=100)
                response.raise_for_status();value=response.json();choice=value['choices'][0]
                if value.get('model')!=CAPACITY_MODEL or choice['finish_reason']!='stop' or choice['message'].get('refusal'):
                    raise ValueError('Incomplete or unexpected response model')
                obs['cases'].append({'case_id':case['id'],'arm':arm,'text':json.loads(choice['message']['content'])['text'],
                                     'elapsed_ms':(time.monotonic()-start)*1000,'response':value});save()
            print(json.dumps({'case':case['id'],'paired_complete':True}),flush=True)
    except Exception as exc:obs['errors'].append(type(exc).__name__+': '+str(exc));save()
    finally:
        signal.alarm(0)
        r=httpx.post(broker['base_url']+'/control/disable-paid',headers=headers,timeout=100);r.raise_for_status()
        (p/'calls-final.json').write_text(json.dumps(r.json()['calls'],indent=2));save()
    deck=[];mapping={}
    for case in fixtures:
        rows=[r for r in obs['cases'] if r['case_id']==case['id']];random.SystemRandom().shuffle(rows)
        for i,row in enumerate(rows):
            label=case['id']+'-'+chr(65+i);mapping[label]=row['arm']
            deck.append({'label':label,'text':row['text'],'task':case['task'],'memory_evidence':case['memory_evidence'],'oracle':case['oracle'],'origin':case['origin']})
    (p/'review-deck.json').write_text(json.dumps(deck,indent=2));(p/'review-mapping.json').write_text(json.dumps(mapping,indent=2))
    print(json.dumps({'awaiting_review':str(p),'errors':obs['errors']}),flush=True)

if __name__=='__main__':run()
