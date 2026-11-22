"""Download pinned public CoreML/tokenizer assets only; never accepts audio."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import urllib.request

REPO='argmaxinc/whisperkit-coreml'
REVISION='0f63a7800b00dd0226abd051b906c246e1907482'
MODEL='openai_whisper-large-v3-v20240930_turbo'
TOKENIZER_REVISION='41f01f3fe87f28c78e2fbf8b568835947dd65ed9'
ROOT=Path('.tavi/models/coreml-turbo')


def get_json(url):
    with urllib.request.urlopen(url,timeout=45) as r:return json.load(r)


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def main():
    tree=get_json(f'https://huggingface.co/api/models/{REPO}/tree/{REVISION}/{MODEL}?recursive=true')
    items=[{'url':f'https://huggingface.co/{REPO}/resolve/{REVISION}/'+x['path'],
            'relative':x['path'].split('/',1)[1],'size':x['size'],
            'sha256':x.get('lfs',{}).get('oid')} for x in tree if x['type']=='file']
    for filename in ('tokenizer.json','tokenizer_config.json','special_tokens_map.json'):
        info=get_json(f'https://huggingface.co/api/models/openai/whisper-large-v3-turbo/tree/{TOKENIZER_REVISION}?recursive=false')
        x=next(x for x in info if x['path']==filename)
        items.append({'url':f'https://huggingface.co/openai/whisper-large-v3-turbo/resolve/{TOKENIZER_REVISION}/{filename}',
                      'relative':'tokenizer/'+filename,'size':x['size'],'sha256':x.get('lfs',{}).get('oid')})
    assert sum(x['size'] for x in items)<1_700_000_000
    ROOT.mkdir(parents=True,exist_ok=True)
    def fetch(item):
        path=ROOT/item['relative'];path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists():
            sha=digest(path)
            if path.stat().st_size!=item['size'] or (item['sha256'] and sha!=item['sha256']):
                raise ValueError('Existing CoreML asset changed; refusing overwrite')
        else:
            partial=path.with_name(path.name+'.partial');h=hashlib.sha256();size=0
            with urllib.request.urlopen(item['url'],timeout=90) as r, partial.open('wb') as out:
                while block:=r.read(1024*1024):
                    size+=len(block)
                    if size>item['size']:raise ValueError('Oversized model download')
                    out.write(block);h.update(block)
            sha=h.hexdigest()
            if size!=item['size'] or (item['sha256'] and sha!=item['sha256']):raise ValueError('Model checksum mismatch')
            partial.replace(path)
        return {'path':str(path),'size':item['size'],'sha256':sha,'source':item['url']}
    with ThreadPoolExecutor(max_workers=3) as pool:files=list(pool.map(fetch,items))
    config=json.loads((ROOT/'config.json').read_text())
    assert config['encoder_layers']==32 and config['decoder_layers']==4 and config['num_mel_bins']==128
    manifest={'repo':REPO,'revision':REVISION,'model':MODEL,'tokenizer_revision':TOKENIZER_REVISION,
       'source_checkpoint':'OpenAI large-v3-turbo (v20240930), unquantized float16 conversion',
       'framework_revision':'1bbc57cb7fe6410248a685b1c5a3c6d56adc2ed4','files':files,'total_bytes':sum(x['size'] for x in files)}
    Path('experiments/coreml-asr/model-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'files':len(files),'bytes':manifest['total_bytes'],'verified':True}))


if __name__=='__main__':main()
