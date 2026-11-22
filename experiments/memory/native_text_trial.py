"""Saved qualified memory -> complete native text -> local K queue reference."""
import asyncio
import hashlib
import json
import time
from experiments.memory.runtime import ROOT,SSD,require_ssd
from experiments.memory.native_voice_trial import Envelope
from experiments.memory.native_text import NativeTextReference,speak_completed
from experiments.memory.decision_contract_v2 import snapshot
from experiments.memory.network_window import probe,clock,qualified
from tavi.storage import Store
from tavi.local_speech import LocalSpeech
from tavi.experiment_workflow import begin,audit


async def run():
    require_ssd();folder,plan=begin(ROOT/'experiments/memory/native-text-protocol.json',run_root=SSD/'runs/scored')
    print(json.dumps({'run':str(folder),'audit':audit(folder)}),flush=True)
    data=json.loads((ROOT/'experiments/memory/native-voice-input.json').read_text())
    store=Store(ROOT/'.tavi/simulation/simulation.sqlite3');envelope=Envelope(store);ref=NativeTextReference(envelope)
    voice=LocalSpeech('kokoro-k-mlx');audio_dir=folder/'audio';audio_dir.mkdir()
    result={'cases':[],'errors':[],'physical_playback':False,'input_kind':'fictional_text_only'}
    def save():
        result['additional_spent_reserved_usd']=(store.used_micro_usd()-envelope.initial)/1e6
        (folder/'observations.json').write_text(json.dumps(result,indent=2)+'\n')
    async def work():
        t=time.monotonic();await voice.prepare();result['voice_prepare_ms']=(time.monotonic()-t)*1000
        t=time.monotonic();await ref.connect();result['connection_ms']=(time.monotonic()-t)*1000;result['session_config']=ref.session
        for row in data['cases']:
            before=probe()
            if not before['ok']:raise RuntimeError('Network preflight failed')
            bound=snapshot(row['task'],row['memory_evidence']);start=clock();t=time.monotonic()
            response=await ref.reply(row['task'],row['memory_evidence'],row['id'])
            response.update(task=row['task'],memory_evidence=row['memory_evidence'],oracle=row['oracle'],chunks=[],
                            historical_context_ms=row['context_ms'])
            result['cases'].append(response)
            try:
                async for chunk in speak_completed(voice,response,row['task'],row['memory_evidence'],issued_snapshot=bound,current_snapshot=snapshot(row['task'],row['memory_evidence'])):
                    ready_ms=(time.monotonic()-t)*1000;audio=chunk.pop('audio')
                    path=audio_dir/f"{row['id']}-{chunk['index']}.wav";path.write_bytes(audio.wav)
                    chunk.update(ready_ms=ready_ms,duration_ms=audio.duration_ms,audio_path=str(path),audio_sha256=hashlib.sha256(audio.wav).hexdigest())
                    response['chunks'].append(chunk)
                response['first_audio_ms']=response['chunks'][0]['ready_ms']
                cursor=response['first_audio_ms']+250;gaps=[]
                for c in response['chunks']:
                    available=c['ready_ms']+250;gaps.append(max(0,available-cursor));cursor=max(cursor,available)+c['duration_ms']
                response['predicted_gap_ms']=sum(gaps)
                response['text_reconstructed']=''.join(c['text'] for c in response['chunks'])==response['text']
                response['composite_context_plus_first_audio_ms']=row['context_ms']+response['first_audio_ms']
            except (ValueError,TypeError,KeyError) as exc:response['blocked']=type(exc).__name__+': '+str(exc)
            end=clock();after=probe();response['network']={'before':before,'after':after,'start':start,'end':end,**qualified(before,after,start,end)}
            save();print(json.dumps({'case':row['id'],'first_audio_ms':response.get('first_audio_ms'),'blocked':response.get('blocked'),'text':response['text']}),flush=True)
    try:await asyncio.wait_for(work(),plan['limits']['maximum_wall_seconds'])
    except Exception as exc:result['errors'].append(type(exc).__name__+': '+str(exc));save()
    finally:await voice.close();await ref.close();save();store.close()
    print(json.dumps({'awaiting_review':str(folder),'errors':result['errors']}),flush=True)


if __name__=='__main__':asyncio.run(run())
