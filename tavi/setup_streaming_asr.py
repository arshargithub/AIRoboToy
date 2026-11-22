"""Explicit public-only model preparation; no speech input or inference."""
import base64
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import requests

import google_crc32c
from moonshine_voice import ModelArch
from moonshine_voice.download import find_model_info,_primary_stt_group


def main():
    if version('moonshine-voice')!='0.1.5':raise ValueError('Unpinned Moonshine package')
    info=find_model_info('en',ModelArch.MEDIUM_STREAMING);group=_primary_stt_group(info)
    expected='https://download.moonshine.ai/model/medium-streaming-en/quantized_26_08_21'
    if group['base_url']!=expected:raise ValueError('Pinned model catalog changed')
    root=Path('.tavi/models/moonshine-medium-streaming-en');root.mkdir(parents=True,exist_ok=True)
    total=sum(x['size'] for x in group['files'])
    if total>300_000_000:raise ValueError('Model download exceeds preparation envelope')
    manifest={'package':'moonshine-voice','version':'0.1.5','model':'medium-streaming-en',
        'model_arch':5,'source':expected,'license':'MIT','catalog':group,'files':[],
        'runtime':'Low-level local-files API, no microphone/downloader/spelling or speaker models',
        'wheel_sha256':'9866b1956d12fff11923ad42f1140bcb314bf05bf8d8576fb7b3aa819ec40e51'}
    for item in group['files']:
        if Path(item['name']).name!=item['name'] or not item['url'].startswith(expected+'/'):
            raise ValueError('Unexpected asset path')
        path=root/item['name'];created=not path.exists()
        if created:
            temp=path.with_name(path.name+'.partial');received=temp.stat().st_size if temp.exists() else 0
            if received>item['size']:raise ValueError('Oversized partial asset')
            # Use the same public HTTP transport as the upstream downloader;
            # this CDN rejects urllib's default request but accepts requests.
            # Bounded range requests also avoid a stalled long CDN transfer.
            with requests.Session() as session,temp.open('ab') as output:
                while received<item['size']:
                    end=min(received+512*1024,item['size'])-1
                    with session.get(item['url'],headers={'Range':f'bytes={received}-{end}'},timeout=30) as response:
                        response.raise_for_status()
                        expected_range=f'bytes {received}-{end}/{item["size"]}'
                        if response.status_code!=206 or response.headers.get('Content-Range')!=expected_range:
                            raise ValueError('Unexpected public range response')
                        block=response.content
                        if len(block)!=end-received+1:raise ValueError('Truncated public range response')
                        output.write(block);output.flush();received+=len(block)
            target=temp
        else:target=path
        crc=google_crc32c.Checksum();sha=hashlib.sha256()
        with target.open('rb') as stream:
            for block in iter(lambda:stream.read(1024*1024),b''):crc.update(block);sha.update(block)
        if target.stat().st_size!=item['size'] or base64.b64encode(crc.digest()).decode()!=item['checksum']:
            raise ValueError('Pinned model checksum mismatch')
        if created:target.replace(path)
        manifest['files'].append({'path':str(path),'size':item['size'],'sha256':sha.hexdigest()})
        print('Verified',item['name'],item['size'],'bytes',flush=True)
    import moonshine_voice
    package=Path(moonshine_voice.__file__).parent
    manifest['runtime_files']=[{'relative':str(p.relative_to(package)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in sorted(package.rglob('*')) if p.is_file() and p.suffix in ('.py','.dylib')]
    license_path=package.parent/'moonshine_voice-0.1.5.dist-info/licenses/LICENSE'
    license_text=license_path.read_text();assert 'MIT' in license_text
    manifest['license_sha256']=hashlib.sha256(license_path.read_bytes()).hexdigest()
    Path('experiments/streaming-asr/LICENSE.moonshine').write_text(license_text)
    Path('experiments/streaming-asr/model-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'files':len(manifest['files']),'bytes':total,'verified':True}),flush=True)


if __name__=='__main__':main()
