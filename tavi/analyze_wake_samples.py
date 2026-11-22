"""Development-only input-level comparison on a user-authorized local collection."""
import argparse,json,time
from pathlib import Path
import numpy as np
from .wake_samples import load_samples
from .wake import SherpaWake
from .acoustics import Silero

def main():
    parser=argparse.ArgumentParser();parser.add_argument('collection',type=Path);args=parser.parse_args()
    data,clips=load_samples(args.collection);model=SherpaWake();vad=Silero(Path('.tavi/models/silero_vad.onnx'),wake_backend='off');results=[]
    for gain in [1,2,4,8]:
        rows=[]
        for clip in clips:
            model.reset();vad.reset();raw=clip['pcm'].astype(np.float32)*gain;clipped=int(np.sum(np.abs(raw)>32767));audio=np.clip(raw,-32768,32767).astype(np.int16)
            audio=np.concatenate([np.zeros(16000,dtype=np.int16),audio,np.zeros(16000,dtype=np.int16)]);hits=[];max_speech=0.;speech_frames=0
            for offset in range(0,len(audio),512):
                chunk=np.pad(audio[offset:offset+512],(0,max(0,512-len(audio[offset:offset+512]))));pcm=chunk.tobytes();prob=vad.probability(pcm);max_speech=max(max_speech,prob);speech_frames+=int(prob>=.5)
                if model.feed(pcm):hits.append(round(offset/16000,3))
            rows.append({'number':clip['number'],'label':clip['label'],'detections':hits,'max_speech_probability':max_speech,'speech_frames':speech_frames,'clipped_samples':clipped})
        positives=[r for r in rows if r['label']=='positive'];negatives=[r for r in rows if r['label']=='negative']
        result={'gain':gain,'positive_clips':len(positives),'detected_positive_clips':sum(bool(r['detections']) for r in positives),'negative_clips':len(negatives),'false_wakes':sum(len(r['detections']) for r in negatives),'cases':rows};results.append(result);print(json.dumps({k:v for k,v in result.items() if k!='cases'}),flush=True)
    out=Path('.tavi/private-wake-analysis');out.mkdir(exist_ok=True)
    (out/'input-level-result.json').write_text(json.dumps({'scope':'One local development session; tuning data, not validation','results':results,'api_spend_usd':0},indent=2)+'\n')
if __name__=='__main__':main()
