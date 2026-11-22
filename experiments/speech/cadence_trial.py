"""Prospective zero-spend cadence diagnostic; production settings unchanged."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import time
from experiments.memory.runtime import ROOT,SSD,require_ssd
from experiments.reliability.mac_reliability_trial import status
from experiments.speech.cadence import edges,join,read_pcm,split
from tavi.experiment_workflow import begin,finish,audit,discover_runs,read_protocol,digest
from tavi.local_speech import LocalSpeech
from tavi.inference_schedule import ScheduledSpeech
from tavi.storage import Store


async def synthesize(folder,inputs):
    voice=LocalSpeech('kokoro-k-mlx');speech=ScheduledSpeech(voice,asyncio.get_running_loop());rows=[];process=None
    start=time.monotonic()
    try:
        await speech.prepare();prepare_ms=(time.monotonic()-start)*1000
        for e in inputs['examples']:
            row={'id':e['id'],'text':e['text'],'chunks':[]};rows.append(row)
            for n,text in enumerate(split(e['text'])):
                at=time.monotonic();audio=await speech.synthesize(text);path=folder/f"{e['id']}-{n}.wav";path.write_bytes(audio.wav)
                row['chunks'].append({'text':text,'audio_path':str(path),'audio_sha256':digest(path),'synthesis_ms':(time.monotonic()-at)*1000,**edges(audio.wav)})
            at=time.monotonic();whole=await speech.synthesize(e['text']);whole_path=folder/f"{e['id']}-whole.wav";whole_path.write_bytes(whole.wav)
            combined=join([Path(c['audio_path']).read_bytes() for c in row['chunks']]);combined_path=folder/f"{e['id']}-joined.wav";combined_path.write_bytes(combined)
            row['whole']={'audio_path':str(whole_path),'audio_sha256':digest(whole_path),'synthesis_ms':(time.monotonic()-at)*1000,**edges(whole.wav)}
            row['joined']={'audio_path':str(combined_path),'audio_sha256':digest(combined_path),**edges(combined)}
            row['identical_pcm']=read_pcm(whole.wav)==read_pcm(combined)
            row['boundaries']=[{'after_sequence':n,'threshold_quiet_sum_ms':{db:(row['chunks'][n]['threshold_edges_ms'][db]['trailing_ms']+row['chunks'][n+1]['threshold_edges_ms'][db]['leading_ms'])
                if row['chunks'][n]['threshold_edges_ms'][db]['trailing_ms'] is not None and row['chunks'][n+1]['threshold_edges_ms'][db]['leading_ms'] is not None else None for db in ('-50','-40','-30')}} for n in range(len(row['chunks'])-1)]
        process=voice.process
    finally:await speech.close()
    return {'prepare_ms':prepare_ms,'examples':rows,'worker_closed':voice.process is None and (process is None or process.returncode is not None)}


def run():
    os.umask(0o077);require_ssd();protocol=ROOT/'experiments/speech/cadence-protocol-v1.json';plan=read_protocol(protocol)
    if list((SSD/'runs/scored'/plan['experiment_id']).glob('*/run.json')):raise ValueError('No automatic repeat')
    previous=[audit(p.parent) for p in discover_runs()];before=status()
    if not before['idle'] or not before['family_off']:raise ValueError('Keep active session unchanged')
    folder,plan=begin(protocol,run_root=SSD/'runs/scored');print(json.dumps({'run':str(folder),'audited':len(previous)}),flush=True)
    ledger=Store(ROOT/'.tavi/simulation/simulation.sqlite3',must_exist=True);initial=ledger.used_micro_usd();inputs=json.loads((ROOT/'experiments/speech/cadence-input-v1.json').read_text());data={};errors=[]
    try:
        data['local']=asyncio.run(synthesize(folder,inputs));first=data['local']['examples'][0]
        (folder/'renderer-input.json').write_text(json.dumps({'clips':[c['audio_path'] for c in first['chunks']], 'durations_ms':[c['duration_ms'] for c in first['chunks']], 'conditions':inputs['renderer_conditions']},indent=2)+'\n')
        env=dict(os.environ);env.pop('ELECTRON_RUN_AS_NODE',None);env['PAPRIKA_CADENCE_FOLDER']=str(folder)
        executable=ROOT/'desktop/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron'
        p=subprocess.run([str(executable),str(ROOT/'desktop/test/cadence-probe.cjs')],cwd=ROOT,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=120)
        (folder/'renderer.log').write_text(p.stdout)
        if p.returncode:raise RuntimeError('Muted renderer failed; preserve log')
        data['renderer']=json.loads((folder/'renderer-observations.json').read_text());data['after']=status()
    except Exception as error:errors.append(type(error).__name__+': '+str(error))
    local=data.get('local',{});renderer=data.get('renderer',{});after=data.get('after',{})
    metrics={'examples_completed':len(local.get('examples',[])),'waveforms_completed':sum(len(e['chunks'])+2 for e in local.get('examples',[])),
        'renderer_conditions_completed':len(renderer.get('runs',[])),'worker_closed':local.get('worker_closed'),
        'all_contexts_closed':all(r['context_closed'] for r in renderer.get('runs',[])) if renderer.get('runs') else False,
        'permission_requests':renderer.get('permission_requests'),'physical_audio':renderer.get('physical_audio'),
        'additional_api_usd':(ledger.used_micro_usd()-initial)/1e6,'runtime_idle':after.get('idle'),'family_off':after.get('family_off'),
        'prompt_unchanged':after.get('prompt')==before['prompt'],'collection_errors':len(errors)}
    ledger.close();(folder/'observations.json').write_text(json.dumps({'data':data,'metrics':metrics,'errors':errors},indent=2)+'\n')
    artifacts=[p for p in folder.iterdir() if p.is_file() and p.name not in ('run.json','protocol.json')]
    result=finish(folder,metrics,artifacts=artifacts,completed=not errors,error='; '.join(errors) or None)
    report={'date':'2026-11-10 America/Toronto','run':str(folder),'metrics':metrics,'decision':result['decision'],'audit':audit(folder),'data':data,'errors':errors,
        'critical_review':['Three authored replies and single draws per method are development diagnostics, not a human naturalness test or broad timing estimate.',
            'Thresholded RMS blocks are sensitivity measurements, not exact phoneme or safe trimming boundaries. No sample was removed or gain/punctuation changed.',
            'Actual K worker and current32character chunker; whole-response generation still invokes model per eSpeak sentence. Identity, word stress and naturalness are not inferred from PCM equality or timings.',
            'Actual Chromium/AudioContext and localhost fetch, but prerecorded ready chunks and controlled receipt server; not actual core IPC, live ASR contention or physical acoustic latency. Injected120ms delays are controls, not observed household/network slowness.',
            'Same Mac endpoint source runs with no start/microphone call, zero output gain and muted window. No current app, approved prompt, voice, endpoint or playback policy changes.']}
    (ROOT/'docs/evaluations/paprika_speech_cadence_01.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'decision':result['decision']['outcome'],'metrics':metrics,'errors':errors}),flush=True)


if __name__=='__main__':run()
