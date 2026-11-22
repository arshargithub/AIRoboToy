"""One frozen read-only diagnostic of old synthetic K files, no model or playback."""
import io
from pathlib import Path
import json
import statistics
import time
import unittest
from experiments.memory.runtime import ROOT,SSD,require_ssd
from experiments.memory.prosody_measure import analyze,join,compare
from tavi.experiment_workflow import begin,audit,finish,digest


def run():
    require_ssd();folder,protocol=begin(ROOT/'experiments/memory/prosody-protocol-v1.json',run_root=SSD/'runs/scored')
    print(json.dumps(audit(folder)),flush=True);start=time.monotonic()
    cfg=json.loads((ROOT/'experiments/memory/prosody-input-v1.json').read_text());errors=[];measurements={};joins=[];pairs=[]
    stream=io.StringIO();suite=unittest.defaultTestLoader.loadTestsFromName('tests.test_prosody_measure')
    controls=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite);(folder/'measurement-controls.txt').write_text(stream.getvalue())
    try:
        for asset in cfg['files']:
            path=asset['path'];measurements[path]=analyze(Path(path).read_bytes(),cfg['thresholds_dbfs'],cfg['window_ms'])
        for g in cfg['groups']:
            for a,b in zip(g['clips'],g['clips'][1:]):
                joins.append({'id':g['id'],'left':a['path'],'right':b['path'],**join(measurements[a['path']],measurements[b['path']])})
        for name in cfg['paired_previews']:
            m=json.loads((ROOT/name).read_text())
            for e in m['examples']:
                a,b=e['variants'];pairs.append({'id':e['id'],'methods':[a['method'],b['method']],
                    **compare(Path(a['audio_path']).read_bytes(),Path(b['audio_path']).read_bytes())})
    except Exception as error:errors.append(type(error).__name__+': '+str(error))
    if time.monotonic()-start>protocol['limits']['maximum_wall_seconds']:errors.append('wall_limit')
    unchanged=all(digest(a['path'])==a['sha256'] for a in cfg['files'])
    metrics={'assets_measured':len(measurements),'joins_measured':len(joins),'paired_previews_measured':len(pairs),
        'measurement_controls_passed':controls.testsRun-len(controls.failures)-len(controls.errors),
        'test_failures':len(controls.failures)+len(controls.errors),'collection_errors':len(errors),
        'inputs_unchanged':unchanged,'additional_api_usd':0.0}
    summary={}
    for threshold in cfg['thresholds_dbfs']:
        values=[j['thresholds'][str(threshold)] for j in joins];gaps=[v['low_energy_gap_ms'] for v in values if v['low_energy_gap_ms'] is not None]
        levels=[abs(v['active_window_level_change_db']) for v in values if v['active_window_level_change_db'] is not None]
        summary[str(threshold)]={'join_count':len(gaps),'low_energy_gap_ms':{'min':min(gaps),'median':statistics.median(gaps),'max':max(gaps)},
            'absolute_active_window_level_change_db':{'median':statistics.median(levels),'max':max(levels)}} if gaps else {'join_count':0}
    observation={'metrics':metrics,'assets':measurements,'joins':joins,'paired_previews':pairs,'summary':summary,'errors':errors,
        'model_inference':False,'playback':False,'microphone':False,'audio_written_or_changed':False}
    (folder/'observations.json').write_text(json.dumps(observation,indent=2,allow_nan=False)+'\n')
    record=finish(folder,metrics,artifacts=[folder/'observations.json',folder/'measurement-controls.txt'],completed=not errors,error=';'.join(errors) or None)
    report={'run':str(folder),'metrics':metrics,'summary':summary,'paired_previews':pairs,'joins':joins,'decision':record['decision'],'audit':audit(folder),
        'critical_review':[
            'Reused35synthetic WAVs from old development runs;17response groups/12external joins and3same-word comparisons. Not a random household sample or new human/acoustic evidence.',
            '5ms energy windows at three fixed thresholds measure low-energy padding, not phoneme alignment, true silence or perceived naturalness. Quiet consonants/breath/noise can cross thresholds; do not use this diagnostic as a live trimmer.',
            'Active-window RMS difference is a level proxy, not perceptual loudness or proof of gain normalization as the cause. Sentence content and voice dynamics differ. Sample endpoint step is only a possible click proxy.',
            'Saved concatenated audio contains no network/browser scheduling gap. Live event gaps measured previously are separate and cannot be added to these unrelated recordings as an end-to-end measurement.',
            'Identical or strongly correlated whole-versus-joined files do not demonstrate natural prosody. The frontend segments sentences internally; larger text requests alone need not supply joint sentence context.',
            'No voice/model/rate/endpoint/playback/production defaults changed. Any removal/addition of padding, fades or level smoothing needs a bounded same-text candidate and later owner listening, which is parked.'
        ]}
    (ROOT/'docs/evaluations/paprika_saved_prosody_01.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'run':str(folder),'metrics':metrics,'summary':summary,'pairs':pairs,'outcome':record['decision']['outcome']}),flush=True)


if __name__=='__main__':run()
