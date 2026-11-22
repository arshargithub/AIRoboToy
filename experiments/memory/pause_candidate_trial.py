"""Prepare immutable offline same-audio pause comparisons; never publish as a default."""
import io
import json
import os
from pathlib import Path
import time
import unittest
from experiments.memory.runtime import ROOT,SSD,require_ssd
from experiments.memory.pause_candidate import prepare
from experiments.memory.prosody_measure import analyze,join,pcm
from tavi.experiment_workflow import begin,audit,finish,digest


def write(path,raw):
    with os.fdopen(os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'wb') as f:
        f.write(raw);f.flush();os.fsync(f.fileno())


def run():
    require_ssd();folder,protocol=begin(ROOT/'experiments/memory/pause-candidate-protocol-v1.json',run_root=SSD/'runs/scored')
    print(json.dumps(audit(folder)),flush=True);start=time.monotonic()
    cfg=json.loads((ROOT/'experiments/memory/pause-candidate-input-v1.json').read_text());errors=[];rows=[]
    stream=io.StringIO();controls=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromName('tests.test_pause_candidate'))
    (folder/'controls.txt').write_text(stream.getvalue());audio=folder/'audio';audio.mkdir(mode=0o700)
    try:
        for g in cfg['groups']:
            raws=[Path(a['path']).read_bytes() for a in g['clips']];control,candidate,integrity=prepare(raws)
            before=[analyze(r) for r in raws];after=[]
            rate,values=pcm(candidate);cursor=0
            # Verify encoded candidate segments against each exact retained source slice.
            for original,slice_info in zip(raws,integrity['slices']):
                _,source=pcm(original);expected=source[slice_info['start']:slice_info['end']];actual=values[cursor:cursor+len(expected)]
                if actual!=expected:raise ValueError('Candidate changed retained samples')
                from experiments.memory.pause_candidate import pack
                after.append(analyze(pack(rate,actual)));cursor+=len(expected)
            paths=[]
            for label,raw in [('control',control),('candidate',candidate)]:
                path=audio/f"{g['id']}-{label}.wav";write(path,raw)
                paths.append({'label':label,'path':str(path),'sha256':digest(path),'duration_ms':analyze(raw)['duration_ms']})
            original_join=join(before[0],before[1]);candidate_join=join(after[0],after[1])
            rows.append({'id':g['id'],'text':''.join(a['text'] for a in g['clips']),'integrity':integrity,
                'variants':paths,'original_join':original_join,'candidate_join':candidate_join})
    except Exception as error:errors.append(type(error).__name__+': '+str(error))
    if time.monotonic()-start>protocol['limits']['maximum_wall_seconds']:errors.append('wall_limit')
    metrics={'pairs_completed':len(rows),'measurement_controls_passed':controls.testsRun-len(controls.failures)-len(controls.errors),
        'test_failures':len(controls.failures)+len(controls.errors),'collection_errors':len(errors),
        'integrity_checks_passed':sum(all(r['integrity'][key] for key in ['only_zero_samples_removed','encoded_samples_exact','outer_edges_untouched','nonzero_sequence_identical']) for r in rows),
        'bounded_reductions_passed':sum(all(100<=j['removed_ms']<=250 for j in r['integrity']['joins']) for r in rows),
        'inputs_unchanged':all(digest(a['path'])==a['sha256'] for a in cfg['files']),'additional_api_usd':0.0}
    (folder/'observations.json').write_text(json.dumps({'rows':rows,'metrics':metrics,'errors':errors,'listened':False,'production_changed':False},indent=2)+'\n')
    artifacts=[folder/'observations.json',folder/'controls.txt']+[Path(v['path']) for r in rows for v in r['variants']]
    record=finish(folder,metrics,artifacts=artifacts,completed=not errors,error=';'.join(errors) or None)
    report={'run':str(folder),'metrics':metrics,'rows':rows,'decision':record['decision'],'audit':audit(folder),
        'critical_review':[
            'Three reused synthetic development replies, including previously owner-accepted examples. Selection is diagnostic, not independent or held-out. No human listening of this new candidate yet.',
            'Only contiguous exact-zero PCM at external sentence joins may shrink;100ms retained per side, at most125ms removed per side. Low-energy nonzero phonemes/breath/dynamics are preserved exactly. Internal sentence boundaries within a clip and live transport delays are unchanged.',
            'Less time containing zero samples is not proof of better prosody. Intentional pacing can be useful, especially around comfort or paragraph boundaries. This fixed offline candidate is not punctuation-aware, integrated or selected.',
            'No fade, gain, rate, model, voice, endpoint, text, memory, cloud or live scheduling change. Six new private WAVs stay beside the sealed synthetic experiment; original files unchanged. No family profiles or raw human recordings touched.',
            'Later optional guided same-word listening is needed before adopting pause handling. Family voice collection remains parked; no human action requested now. No E3/E4/E5/E6 acceptance inferred.'
        ]}
    (ROOT/'docs/evaluations/paprika_saved_pause_candidate_01.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'run':str(folder),'metrics':metrics,'outcome':record['decision']['outcome'],
        'pairs':[{'id':r['id'],'removed_ms':sum(j['removed_ms'] for j in r['integrity']['joins']),
        'before_gap_ms':r['original_join']['thresholds']['-45']['low_energy_gap_ms'],
        'after_gap_ms':r['candidate_join']['thresholds']['-45']['low_energy_gap_ms']} for r in rows]}),flush=True)


if __name__=='__main__':run()
