"""Background-only examples, split by independent random seeds."""
from pathlib import Path
import numpy as np
from .custom_wake import Features

def main():
    features=Features();root=Path('.tavi/wake-training')
    for split,n,seed in [('train',120,123),('validation',30,987)]:
        rng=np.random.default_rng(seed);vectors=[]
        for i in range(n):
            amplitude=[0,2,10,40,150,500][i%6]
            x=rng.normal(0,amplitude,32000)
            if i%2:x=np.convolve(x,np.ones(9)/3,mode='same')
            vectors.append(features.extract(np.clip(x,-32768,32767).astype(np.int16)))
        np.savez(root/f'{split}-background.npz',x=np.array(vectors),y=np.zeros(n,dtype=int))
    print('Background-only features ready')
if __name__=='__main__':main()
