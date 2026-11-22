"""Continuous-stream development gate for a trained synthetic candidate.

Threshold selection uses validation voices. Test voices are evaluated once at
that fixed threshold; results cannot be used to silently retune the threshold.
"""
import json,time
from pathlib import Path
import numpy as np
from .custom_wake import CustomWake
from .train_custom_wake import read

def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--validation-only',action='store_true');args=parser.parse_args()
    root=Path('.tavi/models/custom');manifest=json.loads((root/'head.json').read_text())
    if manifest['status']!='trial_candidate':
        print('Fixed-window gate failed; streaming candidate is not eligible');return
    model=CustomWake(root,allow_unqualified=True)
    corpus=json.loads(Path('.tavi/wake-training/corpus.json').read_text())
    challenge={'rows':[]} if args.validation_only else json.loads(Path(manifest.get('challenge_corpus','.tavi/wake-training/challenge/corpus.json')).read_text())
    corpus['rows']=[r for r in corpus['rows'] if r['split'] in ('train','validation')]
    if not args.validation_only:corpus['rows'].extend(json.loads(Path(manifest['test_corpus']).read_text())['rows'])
    corpus['rows'].extend(challenge['rows'])
    results=[];durations=[]
    from .wake import SherpaWake
    baseline=SherpaWake()
    from .acoustics import Silero
    speech_detector=Silero(Path('.tavi/models/silero_vad.onnx'),wake_backend='off')
    # Only held-out voice sets, no training clips.
    for row in (r for r in corpus['rows'] if r['split']!='train'):
        model.reset();baseline.reset();speech_detector.reset();raw=read(row['path']);audio=raw;audio=np.concatenate((np.zeros(16000,dtype=np.int16),audio,np.zeros(32000,dtype=np.int16)))
        hits=[];baseline_hits=[];max_score=0.
        for offset in range(0,len(audio),512):
            chunk=audio[offset:offset+512];chunk=np.pad(chunk,(0,512-len(chunk)))
            started=time.perf_counter();speech_detector.probability(chunk.tobytes());event=model.feed(chunk.tobytes(),speech_allowed=max(speech_detector.speech_recent)>=.5);durations.append((time.perf_counter()-started)*1000)
            max_score=max(max_score,model.score)
            if event:hits.append((offset+512)/16000)
            if row['split']=='test' and baseline.feed(chunk.tobytes()):baseline_hits.append((offset+512)/16000)
        if len(results)%15==0:print('Streaming evaluation',len(results),'clips complete',flush=True)
        results.append({'split':row['split'],'voice':row['voice'],'label':row['label'],'text':row['text'],'detections':hits,'baseline_detections':baseline_hits,'max_score':max_score,'duration_seconds':len(audio)/16000})
    summary={}
    for split in ['validation','test']:
        positive=[r for r in results if r['split']==split and r['label']==1];negative=[r for r in results if r['split']==split and r['label']==0]
        if not positive:continue
        summary[split]={'positive_clips':len(positive),'detected_positive_clips':sum(bool(r['detections']) for r in positive),'recall':sum(bool(r['detections']) for r in positive)/len(positive),'negative_clips':len(negative),'false_wakes':sum(len(r['detections']) for r in negative),'negative_audio_seconds':sum(r['duration_seconds'] for r in negative),'duplicate_positive_events':sum(max(0,len(r['detections'])-1) for r in positive)}
    challenge_rows=[r for r in results if r['split']=='challenge']
    test_rows=[r for r in results if r['split']=='test']
    summary['baseline_test']={'positive_clips':sum(r['label']==1 for r in test_rows),'detected_positive_clips':sum(bool(r['baseline_detections']) for r in test_rows if r['label']==1),'negative_clips':sum(r['label']==0 for r in test_rows),'false_wakes':sum(len(r['baseline_detections']) for r in test_rows if r['label']==0)}
    summary['challenge']={'clips':len(challenge_rows),'false_wakes':sum(len(r['detections']) for r in challenge_rows),'audio_seconds':sum(r['duration_seconds'] for r in challenge_rows)}
    summary['frame_processing_ms']={'p95':float(np.percentile(durations,95)),'max':max(durations),'samples':len(durations)}
    passed=all(summary[s]['recall']>=.9 and summary[s]['false_wakes']==0 and summary[s]['duplicate_positive_events']==0 for s in (['validation'] if args.validation_only else ['validation','test'])) and summary['challenge']['false_wakes']==0 and summary['frame_processing_ms']['p95']<32
    manifest['streaming_status']=('validation_passed' if args.validation_only else 'passed') if passed else 'rejected';manifest['streaming_summary']=summary
    (root/'head.json').write_text(json.dumps(manifest,indent=2)+'\n')
    Path('.tavi/wake-training/'+('validation-streaming-result.json' if args.validation_only else 'streaming-result.json')).write_text(json.dumps({'scope':'Synthetic development; not family/room/8-hour qualification','threshold':model.threshold,'summary':summary,'cases':results,'api_spend_usd':0},indent=2)+'\n')
    print(json.dumps({'passed':passed,'summary':summary},indent=2),flush=True)

if __name__=='__main__':main()
