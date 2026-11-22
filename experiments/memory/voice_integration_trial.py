"""Current-window native recall -> guarded complete reply -> sentence K screen.

Fictional development data only. No capture, browser playback or live promotion.
"""
import asyncio
import hashlib
import json
import os
import signal
import sqlite3
import time
from pathlib import Path
from experiments.memory.runtime import ROOT, SSD, CAPACITY_MODEL, require_ssd
from experiments.memory.pilot import Process
from experiments.memory.context_envelope import pack
from experiments.memory.reply_boundary import qualify_context
from experiments.memory.decision_contract_v2 import DECISION_MISSION, SCHEMA, snapshot
from experiments.memory.voice_queue import chunks
from experiments.memory.network_window import probe, clock, qualified
from tavi.local_speech import LocalSpeech
from tavi.experiment_workflow import begin, audit


async def run():
    import httpx, tiktoken
    require_ssd(); os.environ['TIKTOKEN_CACHE_DIR'] = str(SSD/'models/tiktoken')
    folder, plan = begin(ROOT/'experiments/memory/voice-integration-protocol.json',run_root=SSD/'runs/scored')
    print(json.dumps({'run':str(folder),'audit':audit(folder)}),flush=True)
    fixture=json.loads((ROOT/'experiments/memory/decision-v2-input.json').read_text())
    config=json.loads((ROOT/'experiments/memory/voice-integration-input.json').read_text())
    broker=json.loads((SSD/'private-config/broker.json').read_text())
    headers={'Authorization':'Bearer '+broker['token']}
    directory=Path(config['native_directory'])
    db=sqlite3.connect(f'file:{directory}/source-ledger.sqlite3?mode=ro',uri=True)
    sources=[json.loads(r[0]) for r in db.execute('SELECT body FROM episodes WHERE complete=1 AND deleted=0')]; db.close()
    expected=[e for e in fixture['episodes'] if e['speaker_id']!='unknown']
    if sorted(sources,key=lambda s:s['id']) != sorted(expected,key=lambda s:s['id']):
        raise ValueError('Native source generation differs from frozen fixture')
    logs=folder/'logs';logs.mkdir();audio_dir=folder/'audio';audio_dir.mkdir()
    result={'cases':[],'errors':[],'source_generation_sha256':hashlib.sha256(json.dumps(sources,sort_keys=True).encode()).hexdigest()}
    voice=LocalSpeech('kokoro-k-mlx');worker=None;enc=tiktoken.get_encoding('o200k_base')
    def save(): (folder/'observations.json').write_text(json.dumps(result,indent=2)+'\n')
    def send(request):
        value=worker.send(request,timeout=90)
        if not value['ok']:raise RuntimeError(value['error'])
        return value['result']
    async def work():
        nonlocal worker
        t=time.monotonic();await voice.prepare();result['voice_prepare_ms']=(time.monotonic()-t)*1000
        worker=Process('hindsight',directory,logs,'guarded_worker.py');send({'op':'initialize'})
        cases=[{'id':c['id'],'case':c,'oracle':c['oracle'],'origin':'reused development question; fresh native recall'} for c in fixture['cases']]
        cases += fixture['regressions']
        for item in cases:
            before=probe()
            if not before['ok']:raise RuntimeError('Preflight network failed; no reply sent')
            start=time.monotonic()
            if 'case' in item:
                c=item['case'];native=send({'op':'query','question':c,'people':fixture['people']})
                packed=pack('hindsight',native['native_context'],sources,c['audience_ids'],enc)
                evidence=json.loads(packed['context'])
                task={'actual_speaker_id':c['asker'],'people':fixture['people'],'audience_ids':c['audience_ids'],
                      'conversation_at':c['at'],'question':c['text'],'recent_conversation':[],'catalogue':c['catalogue']}
                canonical=sources
            else:
                task=item['task'];evidence=item['memory_evidence'];native=None;packed=None
                canonical=config['regression_sources'][item['id']]
            boundary=qualify_context(task,evidence,canonical);evidence=boundary['evidence']
            bound=snapshot(task,evidence);context_ms=(time.monotonic()-start)*1000
            call_start=clock();t=time.monotonic()
            response=httpx.post(broker['base_url']+'/evaluator/v1/chat/completions',headers=headers,json={
                'model':CAPACITY_MODEL,'store':False,'reasoning_effort':'low','max_completion_tokens':2048,
                'messages':[{'role':'system','content':DECISION_MISSION},
                            {'role':'user','content':json.dumps({'task':task,'memory_evidence':evidence})}],
                'response_format':{'type':'json_schema','json_schema':{'name':'memory_reply','strict':True,'schema':SCHEMA}}},timeout=100)
            call_end=clock();reply_ms=(time.monotonic()-t)*1000
            response.raise_for_status();raw=response.json();choice=raw['choices'][0]
            if raw.get('model')!=CAPACITY_MODEL or choice['finish_reason']!='stop' or choice['message'].get('refusal'):
                raise ValueError('Incomplete reply or unexpected model')
            value=json.loads(choice['message']['content'])
            row={'id':item['id'],'task':task,'memory_evidence':evidence,'boundary':boundary,
                 'native':native,'packed':packed,'origin':item['origin'],'oracle':item['oracle'],
                 'value':value,'response':raw,'context_ms':context_ms,'reply_ms':reply_ms,'chunks':[]}
            # Row exists before synthesis, so a failure remains in the denominator.
            result['cases'].append(row);save()
            try:
                async for chunk in chunks(voice,value,task,evidence,issued_snapshot=bound,current_snapshot=snapshot(task,evidence)):
                    ready_ms=(time.monotonic()-start)*1000
                    audio=chunk.pop('audio');path=audio_dir/f"{item['id']}-{chunk['index']}.wav";path.write_bytes(audio.wav)
                    chunk.update(ready_ms=ready_ms,duration_ms=audio.duration_ms,audio_path=str(path),
                                 audio_sha256=hashlib.sha256(audio.wav).hexdigest())
                    row['chunks'].append(chunk)
                row['first_audio_ready_ms']=row['chunks'][0]['ready_ms']
                cursor=row['first_audio_ready_ms']+250;gaps=[]
                for c in row['chunks']:
                    available=c['ready_ms']+250;gaps.append(max(0,available-cursor));cursor=max(cursor,available)+c['duration_ms']
                row['predicted_gap_ms']=sum(gaps)
                row['text_reconstructed']=''.join(c['text'] for c in row['chunks'])==value['text']
            except (ValueError,TypeError,KeyError) as exc:row['blocked']=type(exc).__name__+': '+str(exc)
            after=probe();row['network']={'before':before,'after':after,'call_start':call_start,'call_end':call_end,**qualified(before,after,call_start,call_end)}
            save();print(json.dumps({'case':item['id'],'first_audio_ms':row.get('first_audio_ready_ms'),'blocked':row.get('blocked')}),flush=True)
    def expired(*_): raise TimeoutError('Integrated trial wall bound')
    signal.signal(signal.SIGALRM,expired); signal.alarm(plan['limits']['maximum_wall_seconds'])
    try:await asyncio.wait_for(work(),plan['limits']['maximum_wall_seconds'])
    except Exception as exc:result['errors'].append(type(exc).__name__+': '+str(exc));save()
    finally:
        signal.alarm(0)
        await voice.close()
        if worker:worker.stop()
        response=httpx.post(broker['base_url']+'/control/disable-paid',headers=headers,timeout=100);response.raise_for_status()
        (folder/'calls-final.json').write_text(json.dumps(response.json()['calls'],indent=2))
        save()
    print(json.dumps({'awaiting_review':str(folder),'errors':result['errors']}),flush=True)


if __name__=='__main__':asyncio.run(run())
