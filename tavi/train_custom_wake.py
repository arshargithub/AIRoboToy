"""Reproducible synthetic-only development experiment; voices are split first."""
import hashlib,json,subprocess,wave,time,inspect,importlib.metadata
from pathlib import Path
import numpy as np
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from .custom_wake import Features,setup

ROOT=Path('.tavi/wake-training')
SPLITS={'train':['Samantha','Daniel','Karen','Fred'],'validation':['Moira'],'test':['Tessa','Kathy']}
POS=['Tah vee.','Hey Tah vee.','Tah vee, hello.']
NEG=['Coffee.','Toffee.','Taffy.','Toby.','TV.','That view.','Have you seen it?','Tell me a story.','Turn off the television.','We are having dinner.','What are you doing?','Thank you very much.']

def read(path):
    with wave.open(str(path),'rb') as wav:
        if (wav.getframerate(),wav.getnchannels(),wav.getsampwidth())!=(16000,1,2):raise ValueError('Fixture format')
        return np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2').copy()

def generate():
    previous={}
    if (ROOT/'corpus.json').exists():
        previous={r['path']:r for r in json.loads((ROOT/'corpus.json').read_text())['rows']}
    rows=[]
    for split,voices in SPLITS.items():
        for voice in voices:
            for label,texts in [(1,POS),(0,NEG)]:
                for rate in ([120,150,180] if label else [130,175]):
                    for index,text in enumerate(texts):
                        path=ROOT/'clips'/f'{voice}-{rate}-{label}-{index}.wav';path.parent.mkdir(parents=True,exist_ok=True)
                        prior=previous.get(str(path),{})
                        valid=path.exists() and all(prior.get(k)==v for k,v in [('text',text),('voice',voice),('label',label)]) and prior.get('sha256')==hashlib.sha256(path.read_bytes()).hexdigest()
                        if not valid:
                            subprocess.run(['/usr/bin/say','-v',voice,'-r',str(rate),'-o',str(path.with_suffix('.aiff')),text],check=True)
                            subprocess.run(['/usr/bin/afconvert','-f','WAVE','-d','LEI16@16000','-c','1',str(path.with_suffix('.aiff')),str(path)],check=True)
                        rows.append(dict(split=split,voice=voice,label=label,text=text,path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
            print('Synthesized',split,voice,flush=True)
    (ROOT/'corpus.json').write_text(json.dumps({'seed':42,'splits':SPLITS,'rows':rows},indent=2)+'\n')
    return rows

def window(audio,rng,augment):
    active=np.flatnonzero(np.abs(audio.astype(np.float32))>180)
    if len(active):audio=audio[max(0,active[0]-400):min(len(audio),active[-1]+400)]
    if augment:
        speed=rng.uniform(.85,1.15);audio=np.interp(np.arange(0,len(audio),speed),np.arange(len(audio)),audio)
    if len(audio)>26000:audio=audio[-26000:]
    x=np.zeros(32000,dtype=np.float32);offset=int(rng.integers(0,max(1,32000-len(audio))))
    x[offset:offset+len(audio)]=audio
    if augment:
        # Gain, mild room tail and low noise. These do not simulate all real rooms.
        x*=rng.uniform(.25,1.0);shift=int(rng.integers(300,1600));x[shift:]+=rng.uniform(.05,.2)*x[:-shift].copy()
        x+=rng.normal(0,rng.uniform(2,40),len(x))
    return np.clip(x,-32768,32767).astype(np.int16)

def feature_signature():
    return {'seed':42,'corpus_sha256':hashlib.sha256((ROOT/'corpus.json').read_bytes()).hexdigest(),
            'frontend_code_sha256':hashlib.sha256(inspect.getsource(Features).encode()).hexdigest(),
            'augmentation_code_sha256':hashlib.sha256(inspect.getsource(window).encode()).hexdigest(),
            'packages':{n:importlib.metadata.version(n) for n in ['numpy','onnxruntime','scikit-learn']}}

def main():
    setup();ROOT.mkdir(parents=True,exist_ok=True);rows=generate();features=Features();rng=np.random.default_rng(42);sets={}
    signature=feature_signature();provenance=ROOT/'feature-provenance.json'
    saved=json.loads(provenance.read_text()) if provenance.exists() else {}
    valid_cache=all(saved.get(k)==v for k,v in signature.items()) and all((ROOT/f'{s}-features.npz').exists() and saved.get('feature_caches',{}).get(f'{s}-features.npz')==hashlib.sha256((ROOT/f'{s}-features.npz').read_bytes()).hexdigest() for s in SPLITS)
    for split in SPLITS:
        cache=ROOT/f'{split}-features.npz'
        if valid_cache:
            with np.load(cache,allow_pickle=False) as a:sets[split]=(a['x'],a['y'])
            continue
        x=[];y=[]
        for row in (r for r in rows if r['split']==split):
            for _ in range((12 if row['label'] else 4) if split=='train' else 3):
                x.append(features.extract(window(read(row['path']),rng,True)));y.append(row['label'])
        x=np.array(x);y=np.array(y);sets[split]=(x,y);np.savez(cache,x=x,y=y);print('Features',split,x.shape,flush=True)
    signature['feature_caches']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.glob('*-features.npz')}
    provenance.write_text(json.dumps(signature,indent=2)+'\n')
    x,y=sets['train'];scale=StandardScaler().fit(x)
    model=MLPClassifier(hidden_layer_sizes=(64,32),alpha=.05,max_iter=350,random_state=42,early_stopping=True,n_iter_no_change=20).fit(scale.transform(x),y)
    vx,vy=sets['validation'];scores=model.predict_proba(scale.transform(vx))[:,1]
    candidates=[]
    for threshold in [.5,.6,.7,.8,.9,.95,.98,.99]:
        pred=scores>=threshold;recall=float(pred[vy==1].mean());false=float(pred[vy==0].mean());candidates.append(dict(threshold=threshold,recall=recall,false_positive_fraction=false))
    valid=[c for c in candidates if c['false_positive_fraction']==0]
    selected=max(valid,key=lambda c:(c['recall'],-c['threshold'])) if valid else min(candidates,key=lambda c:(c['false_positive_fraction'],-c['recall']))
    threshold=selected['threshold'];tx,ty=sets['test'];test_scores=model.predict_proba(scale.transform(tx))[:,1];test_pred=test_scores>=threshold
    report={'scope':'Synthetic fixed-window experiment, not streaming or family acceptance','splits':SPLITS,'training_samples':len(y),'validation_candidates':candidates,'selected':selected,'test':{'positive_windows':int(sum(ty==1)),'negative_windows':int(sum(ty==0)),'recall':float(test_pred[ty==1].mean()),'false_positive_fraction':float(test_pred[ty==0].mean())},'api_spend_usd':0}
    out=Path('.tavi/models/custom');weights={'mean':scale.mean_.astype(np.float32),'scale':scale.scale_.astype(np.float32)}
    for i,(w,b) in enumerate(zip(model.coefs_,model.intercepts_)):weights[f'w{i}']=w.astype(np.float32);weights[f'b{i}']=b.astype(np.float32)
    np.savez(out/'head.npz',**weights)
    passed=selected['recall']>=.9 and selected['false_positive_fraction']==0 and report['test']['recall']>=.9 and report['test']['false_positive_fraction']==0
    manifest={'status':'trial_candidate' if passed else 'rejected','threshold':threshold,'sha256':hashlib.sha256((out/'head.npz').read_bytes()).hexdigest(),'report':report}
    (out/'head.json').write_text(json.dumps(manifest,indent=2)+'\n');(ROOT/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(manifest,indent=2),flush=True)

if __name__=='__main__':main()
