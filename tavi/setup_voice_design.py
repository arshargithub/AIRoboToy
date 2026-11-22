"""Explicit inbound download of the pinned public VoiceDesign experiment assets."""
import hashlib
import json
from pathlib import Path
import urllib.request


def install(manifest_path,root):
    manifest=json.loads(manifest_path.read_text())
    root.mkdir(parents=True,exist_ok=True)
    for row in manifest['files']:
        relative=Path(row['path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Unsafe model path')
        path=root/relative;path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists():
            if path.stat().st_size!=row['size'] or hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:
                raise ValueError('Existing asset differs; preserve and inspect: '+str(path))
            continue
        partial=path.with_name(path.name+'.partial');digest=hashlib.sha256();size=0
        # Preserve interrupted partial downloads for inspection; never load them.
        with urllib.request.urlopen(row['url'],timeout=60) as source,partial.open('xb') as target:
            while chunk:=source.read(1024*1024):
                size+=len(chunk)
                if size>row['size']:raise ValueError('Download exceeded pinned size')
                digest.update(chunk);target.write(chunk)
        if size!=row['size'] or digest.hexdigest()!=row['sha256']:
            raise ValueError('Download failed pinned size/hash verification')
        partial.replace(path)
        print('Verified '+row['path'],flush=True)
    (root/'download-manifest.json').write_bytes(manifest_path.read_bytes())
    print('Pinned local model assets ready. No inference, microphone or paid API request.')


def main():
    install(Path(__file__).with_name('voice_design_manifest.json'),Path('.tavi/models/qwen3-voice-design-4bit'))


if __name__=='__main__':main()
