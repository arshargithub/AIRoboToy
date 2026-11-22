"""Download only pinned public MLX weights/config; no audio or inference."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import urllib.request

MODELS = {
    'base.en': ('whisper-base.en-mlx','aa0678c3466ed62c5c6114ec600a0e1f96820089','weights.npz',143723132,'b6c8ee500656e04e8e57c2949a5253f0dda002ba36cd1561846574dbcf01132e'),
    'small.en': ('whisper-small.en-mlx','52a88bf6e98b114a210c21bb83e22d6e1505cb73','weights.npz',481306200,'1bb29b030aca711a035f7a084a0eefac6251ecc2bdd356fa748858fbad082f5a'),
    'medium.en': ('whisper-medium.en-mlx','8d0335069b551e8586b8a4680674403d9417dfe4','weights.npz',1524923056,'66cda8c3df03af0b922764620d46734240ab82c54348c5848238c8604bdadbdb'),
    'turbo': ('whisper-large-v3-turbo','a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb','weights.safetensors',1613977612,'951ed3fc1203e6a62467abb2144a96ce7eafca8fa77e3704fdb8635ff3e7f8a6'),
}
ROOT = Path('.tavi/models/asr-mlx')


def sha256(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def install(item):
    name,(repo,revision,filename,size,digest)=item
    folder=ROOT/name;folder.mkdir(parents=True,exist_ok=True)
    base=f'https://huggingface.co/mlx-community/{repo}/resolve/{revision}/'
    target=folder/filename
    if target.exists():
        if target.stat().st_size!=size or sha256(target)!=digest:
            raise ValueError('Existing model differs from pinned weights; no overwrite')
    else:
        partial=folder/(filename+'.partial');h=hashlib.sha256();count=0
        with urllib.request.urlopen(base+filename,timeout=90) as response, partial.open('wb') as output:
            while block:=response.read(1024*1024):
                count+=len(block)
                if count>size:raise ValueError('Download exceeded declared size')
                output.write(block);h.update(block)
        if count!=size or h.hexdigest()!=digest:raise ValueError('Weight checksum differs')
        partial.replace(target)
    config=urllib.request.urlopen(base+'config.json',timeout=30).read()
    parsed=json.loads(config)
    if parsed.get('quantization') is not None:raise ValueError('Comparison requires unquantized models')
    path=folder/'config.json'
    if path.exists() and path.read_bytes()!=config:raise ValueError('Existing model config changed')
    path.write_bytes(config)
    result={'id':name,'repo':'mlx-community/'+repo,'revision':revision,'path':str(folder),
            'files':{filename:{'size':size,'sha256':digest},'config.json':{'size':len(config),'sha256':hashlib.sha256(config).hexdigest()}},
            'config':parsed}
    print(name,'downloaded and verified',round(size/1e6),'MB',flush=True)
    return result


if __name__=='__main__':
    ROOT.mkdir(parents=True,exist_ok=True)
    with ThreadPoolExecutor(max_workers=2) as pool:models=list(pool.map(install,MODELS.items()))
    manifest={'scope':'Pinned MLX model downloads; no recording or inference','models':models}
    Path('tavi/asr_mlx_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
