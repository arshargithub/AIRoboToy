"""Second predeclared head family; select only on validation, retire old test."""
import hashlib,json,shutil
from pathlib import Path
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
from threadpoolctl import threadpool_limits

def main():
    root=Path('.tavi/wake-training');out=Path('.tavi/models/custom')
    for name in ['head.json','head.npz']:
        dst=out/('mlp-'+name)
        if not dst.exists():shutil.copyfile(out/name,dst)
    tr=np.load(root/'train-features.npz');va=np.load(root/'validation-features.npz')
    bg=np.load(root/'train-background.npz');vbg=np.load(root/'validation-background.npz')
    tx=np.concatenate([tr['x'],bg['x']]);ty=np.concatenate([tr['y'],bg['y']]);vx=np.concatenate([va['x'],vbg['x']]);y=np.concatenate([va['y'],vbg['y']])
    scale=StandardScaler().fit(tx);x=scale.transform(tx);v=scale.transform(vx);candidates=[]
    with threadpool_limits(limits=1):
        for c in [1,10,100]:
            for gamma in ['scale',.001,.01]:
                model=SVC(C=c,gamma=gamma,class_weight='balanced').fit(x,ty);scores=1/(1+np.exp(-model.decision_function(v)))
                for threshold in [.3,.4,.5,.6,.7,.8,.9]:
                    p=scores>=threshold;candidates.append({'C':c,'gamma':gamma,'threshold':threshold,'recall':float(p[y==1].mean()),'false':float(p[y==0].mean())})
        clean=sorted([r for r in candidates if r['false']==0],key=lambda r:(-r['recall'],r['C'],r['threshold']))
        selected=clean[0]
        model=SVC(C=selected['C'],gamma=selected['gamma'],class_weight='balanced').fit(x,ty)
    np.savez(out/'head.npz',mean=scale.mean_.astype(np.float32),scale=scale.scale_.astype(np.float32),sv=model.support_vectors_.astype(np.float32),dual=model.dual_coef_[0].astype(np.float32),intercept=np.array(model.intercept_[0]),gamma=np.array(model._gamma))
    manifest={'status':'trial_candidate' if selected['recall']>=.9 else 'rejected','head_type':'rbf_svm','threshold':selected['threshold'],'sha256':hashlib.sha256((out/'head.npz').read_bytes()).hexdigest(),'selected':selected,'test_corpus':'.tavi/wake-training/final-test/corpus.json','experiment':'background-and-speech-gated-v2','previous_test_retired':True,'streaming_status':'pending','validation_grid':candidates,'api_spend_usd':0}
    (out/'head.json').write_text(json.dumps(manifest,indent=2)+'\n');print(json.dumps({k:v for k,v in manifest.items() if k!='validation_grid'},indent=2),flush=True)

if __name__=='__main__':main()
