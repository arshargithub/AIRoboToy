"""Experimental local TAH-vee keyword spotter; E2 acceptance is still required."""
import hashlib
from pathlib import Path

FILES = {
 'encoder-epoch-13-avg-2-chunk-8-left-64.onnx':'307e2f5e87e9d6df4fd058239f4437b6236db7699b9c61decb490f89fb4226d0',
 'joiner-epoch-13-avg-2-chunk-8-left-64.onnx':'76f7a24ed0c08633af14b2ee377f747af880d3b65eeba2cd3f31f3380fb73e8d',
 'tokens.txt':'2d3f32311f9b692b964da3c90e830258d3e78e013cb0c992dbfb15cd5a1a71b0',
 'encoder-epoch-13-avg-2-chunk-8-left-64.int8.onnx':'2ca84d6bfe73e1ea3c9c49f600f7cad1c9ddd423c53c906b8bfe802444dd78d5',
 'decoder-epoch-13-avg-2-chunk-8-left-64.onnx':'63a22dd60f40fff082ac3e09afa507f6787da36df76ded2fbe145fa233e22c21',
 'joiner-epoch-13-avg-2-chunk-8-left-64.int8.onnx':'190d4067b4cc20b72a42a1916e69d92052000fb7051a427ebb1bc72a69207dc1',
}
ARCHIVE_SHA256='68447f4fbc67e70eee3a93961f36e81e98f47aef73ce7e7ca00885c6cd3616a6'
URL='https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20.tar.bz2'

class SherpaWake:
    def __init__(self, root=Path('.tavi/models/wake'), *, precision='int8', threshold=.1, score=2, variants=False, phrase='tavi'):
        if precision not in ('int8','fp32') or not 0 < threshold < 1 or score <= 0:
            raise ValueError('Invalid wake configuration')
        import sherpa_onnx
        import numpy as np
        self.np=np
        for name,digest in FILES.items():
            if hashlib.sha256((root/name).read_bytes()).hexdigest()!=digest:
                raise ValueError('Wake model checksum mismatch')
        if phrase not in ('tavi','hey_tavi'):raise ValueError('Unknown wake phrase')
        keywords=root/f'{phrase}-{precision}-{threshold}-{score}-{variants}.txt'
        prefix='HH EY1 ' if phrase=='hey_tavi' else ''
        keyword='HEY_TAVI' if prefix else 'TAVI'
        keywords.write_text(prefix+'T AA1 V IY0 @'+keyword+'\n' + (prefix+'T AA1 V IY1 @'+keyword+'\n' if variants else ''))
        suffix='.int8.onnx' if precision=='int8' else '.onnx'
        self.spotter=sherpa_onnx.KeywordSpotter(tokens=str(root/'tokens.txt'),
            encoder=str(root/('encoder-epoch-13-avg-2-chunk-8-left-64'+suffix)),
            decoder=str(root/'decoder-epoch-13-avg-2-chunk-8-left-64.onnx'),
            joiner=str(root/('joiner-epoch-13-avg-2-chunk-8-left-64'+suffix)),
            keywords_file=str(keywords),num_threads=1,keywords_score=score,keywords_threshold=threshold,num_trailing_blanks=1)
        self.reset()
    def reset(self):
        self.stream=self.spotter.create_stream()
    def feed(self, pcm):
        self.stream.accept_waveform(16000,self.np.frombuffer(pcm,dtype='<i2').astype(self.np.float32)/32768)
        result=''
        while self.spotter.is_ready(self.stream):
            self.spotter.decode_stream(self.stream)
            word=self.spotter.get_result(self.stream)
            if word:
                result=word
                self.spotter.reset_stream(self.stream)
        return result

def setup():
    import json,tarfile
    from urllib.request import urlopen
    archive=Path('.tavi/models/wake.tar.bz2');archive.parent.mkdir(parents=True,exist_ok=True)
    if not archive.exists():
        with urlopen(URL,timeout=60) as r:data=r.read(80_000_000)
        if hashlib.sha256(data).hexdigest()!=ARCHIVE_SHA256:raise ValueError('Wake archive checksum mismatch')
        archive.write_bytes(data)
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=ARCHIVE_SHA256:raise ValueError('Wake archive checksum mismatch')
    root=archive.parent/'wake';root.mkdir(exist_ok=True)
    with tarfile.open(archive) as tar:
        for name,digest in FILES.items():
            member=next(m for m in tar.getmembers() if m.isfile() and Path(m.name).name==name)
            data=tar.extractfile(member).read()
            if hashlib.sha256(data).hexdigest()!=digest:raise ValueError('Wake file checksum mismatch')
            (root/name).write_bytes(data)
    (root/'manifest.json').write_text(json.dumps({'source':URL,'archive_sha256':ARCHIVE_SHA256,'files':FILES,'keyword':'T AA1 V IY0 @TAVI','threshold':.1,'score':2,'qualification':'experimental; family acceptance pending'},indent=2)+'\n')
    print('Experimental local Tavi wake model ready')

if __name__=='__main__':setup()
