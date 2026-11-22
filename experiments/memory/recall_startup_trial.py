"""Three fresh clients, two repeated reads each; server remains warm.
Profiling has overhead; results diagnose lifecycle, not product latency.
"""
import json,time
from pathlib import Path
import httpx
from experiments.memory.runtime import ROOT,SSD
from experiments.memory.pilot import Process
from tavi.storage import Store
from tavi.experiment_workflow import begin,audit,finish

def run():
 folder,plan=begin(ROOT/'experiments/memory/recall-startup-protocol.json',run_root=SSD/'runs/scored');print(audit(folder),flush=True)
 source=json.loads((ROOT/'experiments/memory/combined-input-v1.json').read_text())['cases'][0]
 fixture=json.loads((ROOT/'experiments/memory/decision-v2-input.json').read_text())
 directory=Path(json.loads((ROOT/'experiments/memory/voice-integration-input.json').read_text())['native_directory'])
 q={'id':'startup','text':source['text'],'asker':source['speaker'],'audience_ids':['a','b','c','d'],'at':'2026-09-20T12:00:00Z'}
 result={'rows':[],'errors':[]};store=Store(ROOT/'.tavi/simulation/simulation.sqlite3');initial=store.used_micro_usd();worker=None
 def health():
  r=httpx.get('http://127.0.0.1:8790/health',timeout=3,trust_env=False);r.raise_for_status();v=r.json()
  if v['paid_enabled']:raise ValueError('Paid gateway must remain disabled')
  return v
 def send(body):
  r=worker.send(body,timeout=30)
  if not r['ok']:raise ValueError(r['error'])
  return r['result']
 try:
  result['health_before']=health();deadline=time.monotonic()+100
  for cycle in range(3):
   if time.monotonic()>deadline:raise TimeoutError('Trial bound')
   logs=folder/f'logs{cycle}';logs.mkdir();worker=Process('hindsight',directory,logs,'recall_profile_worker.py')
   t=time.monotonic();send({'op':'initialize'});init=(time.monotonic()-t)*1000
   for index in range(2):
    r=send({'op':'query','question':q,'people':fixture['people']});result['rows'].append({'cycle':cycle,'index':index,'initialize_ms':init,**r})
    print(json.dumps({'cycle':cycle,'index':index,'ms':r['profiled_wall_ms']}),flush=True)
   worker.stop();worker=None
  result['health_after']=health()
 except Exception as e:result['errors'].append(type(e).__name__+': '+str(e))
 finally:
  if worker:worker.stop()
  result['additional_micro_usd']=store.used_micro_usd()-initial;store.close()
 path=folder/'observations.json';path.write_text(json.dumps(result,indent=2)+'\n')
 metrics={'rows':len(result['rows']),'errors':len(result['errors']),'additional_micro_usd':result['additional_micro_usd'],'gateway_new_calls':result.get('health_after',{}).get('calls',-1)-result.get('health_before',{}).get('calls',0)}
 record=finish(folder,metrics,artifacts=[path],completed=not result['errors'],error='; '.join(result['errors']) or None)
 print(json.dumps({'run':str(folder),'metrics':metrics,'audit':audit(folder)}),flush=True)
if __name__=='__main__':run()
