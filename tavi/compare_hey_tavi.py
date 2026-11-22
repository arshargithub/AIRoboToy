"""Bounded longer-phrase comparison; no live activation or threshold tuning."""
import json,wave
from pathlib import Path
import numpy as np
import sherpa_onnx

ROOT=Path('.tavi/models/wake')
def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--extended',action='store_true');args=parser.parse_args()
    keywords=ROOT/'hey-tavi.txt';keywords.write_text('HH EY1 T AA1 V IY0 @HEY_TAVI\nHH EY1 T AA1 V IY1 @HEY_TAVI\n')
    model=sherpa_onnx.KeywordSpotter(tokens=str(ROOT/'tokens.txt'),encoder=str(ROOT/'encoder-epoch-13-avg-2-chunk-8-left-64.int8.onnx'),decoder=str(ROOT/'decoder-epoch-13-avg-2-chunk-8-left-64.onnx'),joiner=str(ROOT/'joiner-epoch-13-avg-2-chunk-8-left-64.int8.onnx'),keywords_file=str(keywords),num_threads=1,keywords_score=2,keywords_threshold=.1,num_trailing_blanks=1)
    corpus=json.loads(Path('.tavi/wake-training/final-test/corpus.json').read_text())['rows']
    challenge=json.loads(Path('.tavi/wake-training/final-challenge/corpus.json').read_text())['rows']
    if args.extended:
        corpus+=json.loads(Path('.tavi/wake-training/corpus.json').read_text())['rows']+json.loads(Path('.tavi/wake-training/fresh-test/corpus.json').read_text())['rows']
        challenge+=json.loads(Path('.tavi/wake-training/challenge/corpus.json').read_text())['rows']
    results=[]
    for row in corpus+challenge:
        expected=row['text']=='Hey Tah vee.'
        with wave.open(row['path'],'rb') as w:audio=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').astype(np.float32)/32768
        audio=np.concatenate([np.zeros(16000,dtype=np.float32),audio,np.zeros(32000,dtype=np.float32)])
        stream=model.create_stream();hits=0
        for offset in range(0,len(audio),512):
            stream.accept_waveform(16000,audio[offset:offset+512])
            while model.is_ready(stream):
                model.decode_stream(stream)
                if model.get_result(stream):hits+=1;model.reset_stream(stream)
        results.append({'voice':row['voice'],'text':row['text'],'expected':expected,'detections':hits})
    pos=[r for r in results if r['expected']];neg=[r for r in results if not r['expected']]
    report={'scope':'Synthetic fixed-configuration longer-phrase comparison; not family acceptance','threshold':.1,'score':2,'positive_clips':len(pos),'detected_positive_clips':sum(bool(r['detections']) for r in pos),'negative_clips':len(neg),'false_wakes':sum(r['detections'] for r in neg),'cases':results,'api_spend_usd':0}
    Path('.tavi/wake-training/'+('hey-tavi-extended-result.json' if args.extended else 'hey-tavi-result.json')).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k!='cases'},indent=2),flush=True)
if __name__=='__main__':main()
