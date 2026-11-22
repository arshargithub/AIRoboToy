"""English-only wake challenger on synthetic development fixtures."""
from pathlib import Path

def setup_model():
    import hashlib,json,tarfile
    from urllib.request import urlopen
    manifest=json.loads(Path(__file__).with_name('model_manifests').joinpath('english-wake.json').read_text())
    root=Path('.tavi/models/english-wake');root.mkdir(parents=True,exist_ok=True)
    archive=root.parent/'english-wake.tar.bz2'
    if not archive.exists():
        with urlopen(manifest['url'],timeout=60) as response:data=response.read(60_000_000)
        if hashlib.sha256(data).hexdigest()!=manifest['archive_sha256']:raise ValueError('Model archive checksum mismatch')
        archive.write_bytes(data)
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=manifest['archive_sha256']:raise ValueError('Model archive checksum mismatch')
    with tarfile.open(archive) as tar:
        for name,digest in manifest['files'].items():
            path=root/name
            if not path.exists():
                member=next(m for m in tar.getmembers() if m.isfile() and Path(m.name).name==name)
                path.write_bytes(tar.extractfile(member).read())
            if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('Model file checksum mismatch')

def main():
    setup_model()
    import sentencepiece as sp,sherpa_onnx,numpy as np,wave,json
    root=Path('.tavi/models/english-wake'); tokenizer=sp.SentencePieceProcessor(model_file=str(root/'bpe.model'))
    keywords=root/'tavi.txt';keywords.write_text('\n'.join(' '.join(tokenizer.encode(text,out_type=str))+' @TAVI' for text in ['TAVI','TAH VEE'])+'\n')
    print(keywords.read_text(),flush=True)
    results=[]
    for threshold,score in [(.25,1),(.1,2)]:
     k=sherpa_onnx.KeywordSpotter(tokens=str(root/'tokens.txt'),encoder=str(root/'encoder-epoch-12-avg-2-chunk-16-left-64.onnx'),decoder=str(root/'decoder-epoch-12-avg-2-chunk-16-left-64.onnx'),joiner=str(root/'joiner-epoch-12-avg-2-chunk-16-left-64.onnx'),keywords_file=str(keywords),num_threads=1,keywords_threshold=threshold,keywords_score=score)
     rows=[]
     for path in sorted(Path('.tavi/audio/wake-comparison').glob('*.wav')):
      stream=k.create_stream();count=0
      with wave.open(str(path),'rb') as w:audio=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').astype(np.float32)/32768
      audio=np.concatenate([audio,np.zeros(16000,dtype=np.float32)])
      for i in range(0,len(audio),512):
       stream.accept_waveform(16000,audio[i:i+512])
       while k.is_ready(stream):
        k.decode_stream(stream)
        if k.get_result(stream):count+=1;k.reset_stream(stream)
      rows.append({'file':path.name,'detections':count})
     result={'threshold':threshold,'score':score,'positive_detections':sum(x['detections'] for x in rows if 'positive' in x['file']),'spoken_names':18,'negative_detections':sum(x['detections'] for x in rows if 'negative' in x['file']),'cases':rows};results.append(result);print(json.dumps({k:v for k,v in result.items() if k!='cases'}),flush=True)
    (root/'comparison.json').write_text(json.dumps({'scope':'Synthetic development event counts; not acceptance accuracy','results':results},indent=2)+'\n')

if __name__ == "__main__":
    main()
