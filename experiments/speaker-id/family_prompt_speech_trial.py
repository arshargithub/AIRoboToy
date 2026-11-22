"""Pre-render authored local prompts; no microphone, playback or cloud."""
import array
import asyncio
import hashlib
from io import BytesIO
import json
import math
import os
from pathlib import Path
import time
from uuid import uuid4
import wave
from experiments.memory.runtime import ROOT,SSD,require_ssd
from tavi.experiment_workflow import begin,audit,finish,digest
from tavi.local_speech import LocalSpeech,validate_wave
from tavi.speaker_profile import VOICE,require_drive,write_json
from tavi.storage import Store


async def run():
    require_ssd();require_drive();folder,plan=begin(ROOT/'experiments/speaker-id/family-prompt-speech-protocol-v1.json',run_root=SSD/'runs/scored')
    print(json.dumps(audit(folder)),flush=True)
    cfg=json.loads((ROOT/'experiments/speaker-id/family-prompt-speech-input-v1.json').read_text())
    output=VOICE/'prompt-audio'/('authored-'+uuid4().hex);output.mkdir(parents=True,mode=0o700,exist_ok=False)
    ledger=Store(ROOT/'.tavi/simulation/simulation.sqlite3');initial=ledger.used_micro_usd()
    voice=LocalSpeech(cfg['backend']);rows=[];errors=[];start=time.monotonic()
    try:
        async with asyncio.timeout(plan['limits']['maximum_wall_seconds']):
            await voice.prepare()
            for item in cfg['prompts']:
                t=time.monotonic();clip=await voice.synthesize(item['text']);validate_wave(clip.wav,24000)
                with wave.open(BytesIO(clip.wav),'rb') as w:
                    samples=array.array('h');samples.frombytes(w.readframes(w.getnframes()))
                peak=max(abs(x) for x in samples)/32768;rms=math.sqrt(sum(x*x for x in samples)/len(samples))/32768
                row={'id':item['id'],'text':item['text'],'text_sha256':hashlib.sha256(item['text'].encode()).hexdigest(),
                     'path':str(output/(item['id']+'.wav')),'sha256':hashlib.sha256(clip.wav).hexdigest(),
                     'duration_ms':clip.duration_ms,'peak':peak,'rms':rms,'clipped_samples':sum(abs(x)>=32767 for x in samples),
                     'render_ms':(time.monotonic()-t)*1000}
                with os.fdopen(os.open(row['path'],os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'wb') as out:out.write(clip.wav);out.flush();os.fsync(out.fileno())
                rows.append(row)
    except Exception as error:errors.append(type(error).__name__+': '+str(error))
    finally:await voice.close()
    metrics={'clips_completed':len(rows),'valid_pcm_24khz':not errors and len(rows)==25,
        'non_silent_and_bounded':bool(rows) and all(r['rms']>.001 and r['peak']<=.96 and 1000<=r['duration_ms']<=12000 for r in rows),
        'text_audio_bindings':sum(digest(r['path'])==r['sha256'] for r in rows),'clipped_samples':sum(r['clipped_samples'] for r in rows),
        'collection_errors':len(errors),'additional_api_usd':(ledger.used_micro_usd()-initial)/1e6}
    ledger.close();(folder/'observations.json').write_text(json.dumps({'metrics':metrics,'rows':rows,'errors':errors,'microphone':False,'playback':False},indent=2)+'\n')
    sealed=finish(folder,metrics,artifacts=[folder/'observations.json']+[Path(r['path']) for r in rows],completed=not errors,error=';'.join(errors) or None)
    if sealed['decision']['outcome']=='pass':
        write_json(ROOT/'experiments/speaker-id/family-prompt-audio-assets-v1.json',{'voice':'provisionalK35MLX','runtime_inference':False,'source_run':str(folder),'prompts':rows,'files':[{'path':r['path'],'sha256':r['sha256']} for r in rows]})
    report={'run':str(folder),'metrics':metrics,'decision':sealed['decision'],'audit':audit(folder),'critical_review':[
        '25authored synthetic question/help prompts rendered locally with unchangedK, no user/child voice or personal memory, no cloud or API spending.',
        'WAV shape/duration/RMS/peak/checksum/text bindings checked, but no human or ASR intelligibility, prosody or child comprehension rating inferred. No acoustic playback by runner.',
        'New immutable private asset directory; only complete passing batch publishes an allowlisted cache manifest. Runtime collection may play it on explicit user action without launching a model.',
        'Question playback must stop before microphone setup/countdown. That ordering is a UI/control guarantee, not independently measured echo suppression or proof no second speaker was captured.',
        'Existing model/style/phoneme assets and isolated Python versions bound. No voice-character change, audition, new speaker threshold or family identity activation.'
    ]}
    (ROOT/'docs/evaluations/paprika_family_prompt_speech_01.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)


if __name__=='__main__':asyncio.run(run())
