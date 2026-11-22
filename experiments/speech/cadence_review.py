"""Zero-inference evidence review and preview generation, no live policy change."""
import json
import os
from pathlib import Path
from experiments.memory.runtime import ROOT,SSD,require_ssd
from experiments.speech.cadence import read_pcm,edges
from experiments.speech.pause_preview import shorten_join_zeros
from experiments.reliability.mac_reliability_trial import status
from tavi.experiment_workflow import begin,finish,audit,discover_runs,read_protocol,digest,evaluate
from tavi.storage import Store


def run():
    os.umask(0o077);require_ssd();path=ROOT/'experiments/speech/cadence-review-protocol-v1.json';plan=read_protocol(path)
    if list((SSD/'runs/scored'/plan['experiment_id']).glob('*/run.json')):raise ValueError('No automatic repeat')
    checks=[audit(p.parent) for p in discover_runs()];before=status()
    if not before['idle'] or not before['family_off']:raise ValueError('Keep app unchanged')
    folder,plan=begin(path,run_root=SSD/'runs/scored');parent=Path(plan['configuration']['parent_run'])
    source=json.loads((parent/'observations.json').read_text());record=json.loads((parent/'run.json').read_text());data={};errors=[]
    ledger=Store(ROOT/'.tavi/simulation/simulation.sqlite3',must_exist=True);initial=ledger.used_micro_usd()
    try:
        failed=[c['metric'] for c in record['decision']['checks'] if not c['passed']]
        if failed!=['additional_api_usd'] or type(source['metrics']['additional_api_usd']) is not float or source['metrics']['additional_api_usd']!=0.0:raise ValueError('Unexpected source failure; no reinterpretation')
        # The evaluator intentionally distinguishes int from float. Correct the
        # prospective review schema, not the immutable parent or its readings.
        revised=json.loads((parent/'protocol.json').read_text())
        for c in revised['criteria']:
            if c['metric']=='additional_api_usd':
                if type(c['equals']) is not int or c['equals']!=0:raise ValueError('Different parent schema')
                c['equals']=0.0
        data['semantic_collection_review']=evaluate(revised,source['metrics'])
        inputs=json.loads((ROOT/'experiments/speech/cadence-input-v1.json').read_text());lookup={e['id']:e for e in inputs['examples']}
        destination=SSD/'previews/speech-cadence-v1';destination.mkdir(mode=0o700,exist_ok=False)
        examples=[];data['previews']=[]
        for i,row in enumerate(source['data']['local']['examples']):
            wavs=[]
            for c in row['chunks']:
                p=Path(c['audio_path'])
                if digest(p)!=c['audio_sha256']:raise ValueError('Source chunk changed')
                wavs.append(p.read_bytes())
            original_path=Path(row['joined']['audio_path'])
            if digest(original_path)!=row['joined']['audio_sha256']:raise ValueError('Source join changed')
            original=original_path.read_bytes();candidate,edits=shorten_join_zeros(wavs)
            paths={};variants=[];order=('original','candidate') if i%2==0 else ('candidate','original')
            for label,method in zip(('a','b'),order):
                out=destination/f"{row['id']}-{label}.wav";out.write_bytes(original if method=='original' else candidate)
                paths[method]=out;variants.append({'id':label,'method':method,'audio_path':str(out),'audio_sha256':digest(out),'duration_ms':edges(out.read_bytes())['duration_ms']})
            a=read_pcm(original);b=read_pcm(candidate)
            data['previews'].append({'id':row['id'],'edits':edits,'removed_ms':(len(a)-len(b))/24,
                'all_nonzero_samples_identical':[v for v in a if v]==[v for v in b if v],
                'preview_files':{method:str(p) for method,p in paths.items()}})
            e=lookup[row['id']];examples.append({'id':e['id'],'title':e['title'],'question':e['question'],'text':e['text'],'variants':variants})
        manifest={'kind':'speech_cadence_preview','source_run':str(parent),'source_sha256':digest(parent/'observations.json'),
            'scope':'Unchanged K and fictional words. A/Bcompare original joined chunks versus preview-only shortening of exact-zero audio at internal joins,max120msperedge,atleast80mszero retained where available. No waveform threshold trimming, new inference, mic or live-system change. Prerecorded comparison omits actual application transport gaps.',
            'focus':'Listen for pauses between sentences. Both versions use the same K recording and words; one has shorter silent joins. Decide which flows more naturally and whether any pause feels rushed. This is optional polish and changes nothing in Paprika.',
            'examples':examples}
        (ROOT/'experiments/speech/cadence-preview-v1.json').write_text(json.dumps(manifest,indent=2)+'\n');data['after']=status()
    except Exception as error:errors.append(type(error).__name__+': '+str(error))
    previews=data.get('previews',[]);after=data.get('after',{})
    metrics={'parent_review_passed':data.get('semantic_collection_review',{}).get('outcome')=='pass','preview_examples':len(previews),
        'all_nonzero_samples_identical':all(p['all_nonzero_samples_identical'] for p in previews) if previews else False,
        'all_edits_only_zero':all(e['removed_samples_were_zero'] and e['kept_body_identical'] and max(e['removed_leading_samples'],e['removed_trailing_samples'])<=2880 for p in previews for e in p['edits']) if previews else False,
        'additional_api_usd':(ledger.used_micro_usd()-initial)/1e6,'runtime_idle':after.get('idle'),'family_off':after.get('family_off'),
        'prompt_unchanged':after.get('prompt')==before['prompt'],'collection_errors':len(errors)}
    ledger.close();(folder/'observations.json').write_text(json.dumps({'metrics':metrics,'data':data,'errors':errors},indent=2)+'\n')
    artifacts=[folder/'observations.json']
    if not errors:artifacts+=[ROOT/'experiments/speech/cadence-preview-v1.json']+[Path(p) for row in previews for p in row['preview_files'].values()]
    result=finish(folder,metrics,artifacts=artifacts,completed=not errors,error='; '.join(errors) or None)
    report={'run':str(folder),'metrics':metrics,'decision':result['decision'],'audit':audit(folder),'data':data,'errors':errors,
        'critical_review':['Parent remains sealed FAIL solely because integer0criterion rejected actual float0.0; all observations/counts unchanged. This review uses exact0.0and does not repeat synthesis/playback.',
            'Candidate changes pause length, a perceptual tradeoff. Preserving every nonzero sample does not establish naturalness; exact-zero gaps can be intentional. Not deployed or owner-approved.',
            'At most120msfrom each internal edge; keep at least80msexact-zero edge where available, firstlead/finaltail unchanged, no gain/time stretch/crossfade or quiet-phoneme threshold.',
            'Original synthesis_ms fields include capture file writing and whole variant join/analysis work; treat as capture-inclusive preparation times, not isolated inference timings.',
            'Three new authored replies, one draw/condition, ready chunks. No household acoustics/livecoreIPC or E3/E6 acceptance. Guided page completion must still be verified separately in QA, never using fake owner ratings.']}
    (ROOT/'docs/evaluations/paprika_speech_cadence_review_01.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'run':str(folder),'decision':result['decision']['outcome'],'metrics':metrics,'errors':errors}),flush=True)


if __name__=='__main__':run()
