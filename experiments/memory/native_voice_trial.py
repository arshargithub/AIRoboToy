"""Same saved qualified contexts through a native speech reference, no playback."""
import asyncio
import hashlib
import json
import time
import wave
from pathlib import Path
from experiments.memory.runtime import ROOT,SSD,require_ssd
from experiments.memory.native_voice import NativeMemoryReference
from experiments.memory.network_window import probe,clock,qualified
from tavi.storage import Store
from tavi.experiment_workflow import begin,audit


class Envelope:
    def __init__(self,store):self.store=store;self.initial=store.used_micro_usd();self.calls=0
    def reserve(self,key,amount,cap):
        if self.calls>=16 or self.store.used_micro_usd()+amount>self.initial+3_000_000:
            raise ValueError('Native memory reference spend/call bound')
        self.store.reserve(key,amount,cap);self.calls+=1
    def settle(self,key,amount):self.store.settle(key,amount)


async def run(protocol=ROOT/'experiments/memory/native-voice-protocol.json'):
    require_ssd();folder,plan=begin(protocol,run_root=SSD/'runs/scored')
    print(json.dumps({'run':str(folder),'audit':audit(folder)}),flush=True)
    data=json.loads((ROOT/'experiments/memory/native-voice-input.json').read_text())
    store=Store(ROOT/'.tavi/simulation/simulation.sqlite3');envelope=Envelope(store);ref=NativeMemoryReference(envelope)
    result={'cases':[],'errors':[],'physical_playback':False,'input_kind':'fictional_text_only'}
    audio_dir=folder/'audio';audio_dir.mkdir()
    def save():
        result['additional_spent_reserved_usd']=(store.used_micro_usd()-envelope.initial)/1e6
        (folder/'observations.json').write_text(json.dumps(result,indent=2)+'\n')
    async def work():
        started=time.monotonic();await ref.connect();result['connection_ms']=(time.monotonic()-started)*1000
        result['session_config']=ref.session
        for row in data['cases']:
            before=probe()
            if not before['ok']:raise RuntimeError('Network preflight failed')
            start=clock()
            response,pcm=await ref.reply(row['task'],row['memory_evidence'],row['id'])
            end=clock();after=probe()
            path=audio_dir/(row['id']+'.wav')
            with wave.open(str(path),'wb') as w:
                w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000);w.writeframes(pcm)
            response.update(task=row['task'],memory_evidence=row['memory_evidence'],oracle=row['oracle'],
                audio_path=str(path),audio_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                network={'before':before,'after':after,'start':start,'end':end,**qualified(before,after,start,end)},
                historical_context_ms=row['context_ms'],
                composite_context_plus_first_audio_ms=row['context_ms']+response['first_audio_ms'])
            result['cases'].append(response);save()
            print(json.dumps({'case':row['id'],'first_audio_ms':response['first_audio_ms'],'text':response['text']}),flush=True)
    try:await asyncio.wait_for(work(),plan['limits']['maximum_wall_seconds'])
    except Exception as exc:result['errors'].append(type(exc).__name__+': '+str(exc));save()
    finally:
        await ref.close();save();store.close()
    print(json.dumps({'awaiting_review':str(folder),'errors':result['errors']}),flush=True)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--protocol',default=str(ROOT/'experiments/memory/native-voice-protocol.json'))
    args=parser.parse_args();asyncio.run(run(args.protocol))
