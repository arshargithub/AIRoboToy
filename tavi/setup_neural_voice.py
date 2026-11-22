"""Install only pinned public voice assets; runtime performs no downloads."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import urllib.request

from .neural_voice import MANIFEST, ROOT, verify_assets


def download(url, path, digest, bound):
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Existing voice asset changed; inspect it before replacing: '+str(path))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.partial')
    with urllib.request.urlopen(url, timeout=60) as response, temporary.open('wb') as output:
        count = 0; actual = hashlib.sha256()
        while chunk := response.read(1024*1024):
            count += len(chunk)
            if count > bound: raise ValueError('Voice download exceeds its bound')
            actual.update(chunk); output.write(chunk)
    if actual.hexdigest() != digest: raise ValueError('Voice asset checksum mismatch')
    temporary.replace(path)


def setup(name):
    entry = json.loads(MANIFEST.read_text())['models'][name]
    root = ROOT/entry['directory']
    if name == 'piper':
        for relative, url in entry['sources'].items():
            download(url, root/relative, entry['files'][relative], 80_000_000)
    else:
        archive_name = entry['directory']+'.tar.bz2'
        archive = ROOT/archive_name
        download('https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/'+archive_name,
                 archive, entry['archive_sha256'], 150_000_000)
        with tarfile.open(archive) as data:
            members = data.getmembers()
            if (sum(m.size for m in members) > 800_000_000 or any(
                not (m.isfile() or m.isdir()) or Path(m.name).is_absolute()
                or '..' in Path(m.name).parts or Path(m.name).parts[0] != entry['directory'] for m in members)):
                raise ValueError('Invalid voice archive members')
            # Do not silently overwrite modified assets on a repeat setup.
            for member in members:
                destination = ROOT/member.name
                if member.isfile() and destination.exists():
                    with data.extractfile(member) as source:
                        if hashlib.sha256(destination.read_bytes()).digest() != hashlib.sha256(source.read()).digest():
                            raise ValueError('Existing voice asset changed: '+member.name)
            data.extractall(ROOT, filter='data')
        if name == 'pocket':
            ref = entry['reference']
            download(ref['url'], root/'alba-casual.wav', ref['sha256'], 2_000_000)
    verify_assets(name)
    print(name+': pinned voice assets verified; no inference or upload')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model', choices=['piper', 'pocket', 'kokoro'], default='piper')
    setup(p.parse_args().model)


if __name__ == '__main__': main()
