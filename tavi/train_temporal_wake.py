"""Sequence-preserving head. Old test sets are explicitly retired to development."""
import hashlib,json,time
from pathlib import Path
import numpy as np
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits
from .custom_wake import Features
from .train_custom_wake import window,read

ROOT=Path('.tavi/wake-training');OUT=Path('.tavi/models/custom')
def main():
    old=json.loads((ROOT/'corpus.json').read_text())['rows']
    fresh=json.loads((ROOT/'fresh-test/corpus.json').read_text())['rows']
    challenge=json.loads((ROOT/'challenge/corpus.json').read_text())['rows']
    rows=[dict(r,split='validation' if r['voice']=='Moira' else 'train') for r in old+fresh+challenge]
    # Retain the challenge vocabulary for validation, rendered by Moira only
    # when available. The former challenge set itself is now training data.
    config={'seed':73,'feature_mode':'temporal','rows':rows,'augmentation':{'positive':36,'negative':12,'validation':3},'final_test':str(ROOT/'final-test/corpus.json')}
    (ROOT/'temporal-corpus.json').write_text(json.dumps(config,indent=2)+'\n')
    f=Features(mode='temporal');sets={};rng=np.random.default_rng(73)
    for split in ['train','validation']:
        cache=ROOT/f'{split}-temporal.npz'
        signature=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()
        if cache.exists():
            with np.load(cache,allow_pickle=False) as a:
                if str(a['signature'])==signature:sets[split]=(a['x'],a['y']);continue
        x=[];y=[]
        for index,row in enumerate(r for r in rows if r['split']==split):
            for _ in range((36 if row['label'] else 12) if split=='train' else 3):
                x.append(f.extract(window(read(row['path']),rng,True)));y.append(row['label'])
            if index%30==0:print('Temporal features',split,index,'clips',flush=True)
        # Add silence/noise anchors with split-specific random draws.
        for i in range(120 if split=='train' else 30):
            amplitude=[0,2,10,40,150,500][i%6];noise=rng.normal(0,amplitude,32000)
            if i%2:noise=np.convolve(noise,np.ones(9)/3,mode='same')
            x.append(f.extract(np.clip(noise,-32768,32767).astype(np.int16)));y.append(0)
        x=np.array(x);y=np.array(y);sets[split]=(x,y);np.savez(cache,x=x,y=y,signature=np.array(signature));print(split,x.shape,flush=True)
    x,y=sets['train'];scale=StandardScaler().fit(x)
    with threadpool_limits(limits=1):
        model=MLPClassifier(hidden_layer_sizes=(128,64),alpha=.1,max_iter=400,random_state=73,early_stopping=True,n_iter_no_change=25).fit(scale.transform(x),y)
    vx,vy=sets['validation'];scores=model.predict_proba(scale.transform(vx))[:,1];candidates=[]
    for threshold in [.3,.4,.5,.6,.7,.8,.9,.95,.98]:
        pred=scores>=threshold;candidates.append({'threshold':threshold,'recall':float(pred[vy==1].mean()),'false':float(pred[vy==0].mean())})
    clean=sorted([c for c in candidates if c['false']==0],key=lambda c:(-c['recall'],c['threshold']))
    selected=clean[0] if clean else min(candidates,key=lambda c:(c['false'],-c['recall']))
    weights={'mean':scale.mean_.astype(np.float32),'scale':scale.scale_.astype(np.float32)}
    for i,(w,b) in enumerate(zip(model.coefs_,model.intercepts_)):weights[f'w{i}']=w.astype(np.float32);weights[f'b{i}']=b.astype(np.float32)
    np.savez(OUT/'head.npz',**weights)
    manifest={'status':'trial_candidate' if selected['recall']>=.9 and selected['false']==0 else 'rejected','feature_mode':'temporal','head_type':'mlp128_64','threshold':selected['threshold'],'sha256':hashlib.sha256((OUT/'head.npz').read_bytes()).hexdigest(),'selected':selected,'validation_grid':candidates,'test_corpus':str(ROOT/'final-test/corpus.json'),'challenge_corpus':str(ROOT/'final-challenge/corpus.json'),'streaming_status':'pending','experiment':'temporal-v3','retired_test_voices':['Tessa','Kathy','Eddy (English (US))','Flo (English (UK))'],'api_spend_usd':0}
    (OUT/'head.json').write_text(json.dumps(manifest,indent=2)+'\n');(ROOT/'temporal-result.json').write_text(json.dumps(manifest,indent=2)+'\n');print(json.dumps(manifest,indent=2),flush=True)

if __name__=='__main__':main()
