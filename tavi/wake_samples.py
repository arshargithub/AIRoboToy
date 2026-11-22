"""Validate local voice downloads without exposing PCM in logs or repository files."""
import base64,json
from pathlib import Path
import numpy as np

MAX_BYTES=12_000_000

def load_samples(path: Path):
    if path.stat().st_size>MAX_BYTES:raise ValueError('Sample collection too large')
    data=json.loads(path.read_text())
    if data.get('kind')!='tavi_private_wake_samples' or data.get('schema_version')!=1 or data.get('sample_rate')!=16000 or data.get('format')!='mono_pcm16le_base64':raise ValueError('Unexpected collection format')
    clips=data.get('clips',[])
    if not isinstance(clips,list) or not 1<=len(clips)<=20:raise ValueError('Invalid clip count')
    decoded=[]
    for i,clip in enumerate(clips,1):
        if clip.get('number')!=i or clip.get('label') not in ('positive','negative'):raise ValueError('Invalid clip labels/order')
        raw=base64.b64decode(clip['pcm_base64'],validate=True)
        if len(raw)%2 or not 16000<=len(raw)//2<=65024 or clip.get('sample_count')!=len(raw)//2:raise ValueError('Invalid PCM size')
        decoded.append({'number':i,'label':clip['label'],'phrase':clip['phrase'],'pcm':np.frombuffer(raw,dtype='<i2').copy()})
    if data.get('complete') and len(clips)!=20:raise ValueError('Incomplete collection marked complete')
    return data,decoded
