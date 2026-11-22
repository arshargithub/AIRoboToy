"""Paired free replay: preserve complete short sentences versus coalescing.

Same complete saved words/K/controller. Synthetic accelerated playback receipts;
no inference provider, microphone, audible playback or full latency acceptance.
"""
import asyncio
import hashlib
import json
import os
import statistics
import time
from experiments.memory.runtime import ROOT,SSD,require_ssd
from tavi.chunked_conversation import ChunkedConversation
from tavi.local_speech import LocalSpeech
from tavi.storage import Store
from tavi.experiment_workflow import begin,finish,audit

async def run():
    require_ssd();folder,plan=begin(ROOT/'experiments/memory/sentence-boundary-protocol.json',run_root=SSD/'runs/scored')
    print(json.dumps({'run':str(folder),'audit':audit(folder)}),flush=True)
    inputs=json.loads((ROOT/'experiments/memory/local-stage-input.json').read_text())
    voice=LocalSpeech('kokoro-k-mlx');store=Store();ledger=Store(ROOT/'.tavi/simulation/simulation.sqlite3');initial=ledger.used_micro_usd()
    result={'rows':[],'errors':[],'physical_playback':False};active=None;audio_dir=folder/'audio';audio_dir.mkdir()
    class Replay:
        async def stream_reply(self,history):yield active['text']
        async def close(self):pass
    def save():(folder/'observations.json').write_text(json.dumps(result,indent=2)+'\n')
    async def work():
        nonlocal active
        start=time.monotonic();await voice.prepare();result['startup_ms']=(time.monotonic()-start)*1000
        for repeat in range(2):
            cases=inputs['cases'] if repeat==0 else list(reversed(inputs['cases']))
            for i,active in enumerate(cases):
                for minimum in ([32,1] if (i+repeat)%2==0 else [1,32]):
                    c=ChunkedConversation(store,provider=Replay(),speech=voice,sentence_minimum=minimum)
                    c.start('replay');start=time.monotonic();rid=None
                    row={'id':active['id'],'repeat':repeat,'minimum':minimum,'load_before':os.getloadavg(),'chunks':[]}
                    result['rows'].append(row)
                    try:
                        c.feed('replay',{'events':[{'type':'speech_started','utterance':1},{'type':'recognition','utterance':1,'text':'Paprika, reply.','final':True}]})
                        rid=c.controller.token.response_id
                        async with asyncio.timeout(35):
                            while c.completed_response_id!=rid:
                                if c.failure:raise ValueError(str(c.failure))
                                if c.audio:
                                    a=c.audio;data=c.audio_bytes('replay',rid,a['sequence'])
                                    part={'sequence':a['sequence'],'text':a['text'],'ready_ms':(a['ready_at']-start)*1000,'duration_ms':a['duration_ms'],'sha256':hashlib.sha256(data).hexdigest()}
                                    if active['id']=='n01' and repeat==0:
                                        p=audio_dir/f"n01-{minimum}-{a['sequence']}.wav";p.write_bytes(data);part['audio_path']=str(p)
                                    row['chunks'].append(part);body={'response_id':rid,'sequence':a['sequence']}
                                    assert c.command('replay','started',body);assert c.command('replay','played',body)
                                await asyncio.sleep(.005)
                        row['first_ms']=row['chunks'][0]['ready_ms'];row['total_synthesis_ms']=row['chunks'][-1]['ready_ms']
                        row['exact_text']=''.join(x['text'] for x in row['chunks'])==active['text']
                        row['history_exact']=c.history[-1]['content']==active['text']
                        cursor=row['first_ms']+250;gaps=[]
                        for x in row['chunks']:
                            available=x['ready_ms']+250;gaps.append(max(0,available-cursor));cursor=max(cursor,available)+x['duration_ms']
                        row['predicted_gap_ms']=sum(gaps);row['load_after']=os.getloadavg()
                    finally:
                        # Retain the common warm voice; retire controller/provider.
                        c.stop()
                        await asyncio.gather(*tuple(c.tasks),return_exceptions=True)
                    save();print(json.dumps({k:row[k] for k in ['id','repeat','minimum','first_ms','total_synthesis_ms']}),flush=True)
    try:await asyncio.wait_for(work(),300)
    except Exception as e:result['errors'].append(type(e).__name__+': '+str(e))
    finally:
        await voice.close();store.close();result['additional_api_usd']=(ledger.used_micro_usd()-initial)/1e6;ledger.close();save()
    pairs={}
    for r in result['rows']:pairs.setdefault((r['id'],r['repeat']),{})[r['minimum']]=r
    complete=[p for p in pairs.values() if len(p)==2 and all('first_ms' in v for v in p.values())]
    target=[p for key,p in pairs.items() if key[0]=='n01' and p in complete]
    metrics={'rows_complete':sum('first_ms' in r for r in result['rows']),'collection_errors':len(result['errors']),
      'text_or_history_errors':sum(not(r.get('exact_text') and r.get('history_exact')) for r in result['rows']),
      'predicted_underruns':sum(r.get('predicted_gap_ms',1)>0 for r in result['rows']),
      'target_first_ratio':statistics.median(p[1]['first_ms']/p[32]['first_ms'] for p in target) if target else None,
      'median_total_work_ratio':statistics.median(p[1]['total_synthesis_ms']/p[32]['total_synthesis_ms'] for p in complete) if complete else None,
      'additional_api_usd':result['additional_api_usd']}
    finish(folder,metrics,artifacts=[folder/'observations.json'],completed=not result['errors'],error='; '.join(result['errors']) or None)
    print(json.dumps({'metrics':metrics,'audit':audit(folder)}),flush=True)

if __name__=='__main__':asyncio.run(run())
