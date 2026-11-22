"""Personalized acoustic-template feasibility, grouped by original utterance.

This is same-session development cross-validation, not family acceptance.
"""
import argparse,json
from pathlib import Path
import numpy as np
from scipy.fft import dct
from .wake_samples import load_samples
from .acoustics import Silero

def mfcc(pcm):
    x=pcm.astype(np.float64)/32768
    x=np.concatenate([x[:1],x[1:]-.97*x[:-1]])
    frames=np.lib.stride_tricks.sliding_window_view(x,400)[::160]*np.hamming(400)
    power=np.abs(np.fft.rfft(frames,n=512))**2
    hz=np.linspace(0,8000,257);mel=lambda h:2595*np.log10(1+h/700)
    edges=700*(10**(np.linspace(mel(80),mel(7600),34)/2595)-1)
    bank=np.zeros((32,257))
    for i in range(32):bank[i]=np.maximum(0,np.minimum((hz-edges[i])/(edges[i+1]-edges[i]),(edges[i+2]-hz)/(edges[i+2]-edges[i+1])))
    c=dct(np.log(np.maximum(power@bank.T,1e-12)),type=2,norm='ortho',axis=1)[:,1:14]
    return np.concatenate([c,np.gradient(c,axis=0)],axis=1).astype(np.float32)

def distance(a,b):
    cost=np.full((len(a)+1,len(b)+1),np.inf);cost[0,0]=0
    distances=np.sqrt(np.mean((a[:,None,:]-b[None,:,:])**2,axis=2))
    for i in range(1,len(a)+1):
        for j in range(max(1,int(i*len(b)/len(a))-12),min(len(b),int(i*len(b)/len(a))+12)+1):
            cost[i,j]=distances[i-1,j-1]+min(cost[i-1,j],cost[i,j-1],cost[i-1,j-1])
    return float(cost[-1,-1]/(len(a)+len(b)))

def main():
    p=argparse.ArgumentParser();p.add_argument('collection',type=Path);a=p.parse_args();_,clips=load_samples(a.collection);vad=Silero(Path('.tavi/models/silero_vad.onnx'),wake_backend='off');features=[]
    for clip in clips:
        vad.reset();speech=[];pcm=clip['pcm']
        for offset in range(0,len(pcm),512):
            part=np.pad(pcm[offset:offset+512],(0,512-len(pcm[offset:offset+512])))
            if vad.probability(part.tobytes())>=.5:speech.append(offset)
        if not speech:raise ValueError('Clip lacks speech')
        crop=pcm[max(0,speech[0]-800):min(len(pcm),speech[-1]+512+800)]
        features.append(mfcc(crop))
    rows=[]
    for i,clip in enumerate(clips):
        # Each held-out recording is excluded entirely; no augmented sibling leakage.
        scale=np.maximum(np.concatenate([f for j,f in enumerate(features) if j!=i]).std(axis=0),1)
        positives=[distance(features[i]/scale,f/scale) for j,f in enumerate(features) if j!=i and clips[j]['label']=='positive']
        negatives=[distance(features[i]/scale,f/scale) for j,f in enumerate(features) if j!=i and clips[j]['label']=='negative']
        positive=float(np.mean(sorted(positives)[:3]));negative=float(np.mean(sorted(negatives)[:3]))
        rows.append({'number':clip['number'],'label':clip['label'],'positive_distance':positive,'negative_distance':negative,'detected':positive<negative})
    pos=[r for r in rows if r['label']=='positive'];neg=[r for r in rows if r['label']=='negative'];report={'scope':'Leave-one-recording-out same-session development; speaker-specific and not acceptance','positive_clips':len(pos),'detected_positive_clips':sum(r['detected'] for r in pos),'negative_clips':len(neg),'false_wakes':sum(r['detected'] for r in neg),'cases':rows,'api_spend_usd':0};Path('.tavi/private-wake-analysis/template-result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k!='cases'}),flush=True)
if __name__=='__main__':main()
