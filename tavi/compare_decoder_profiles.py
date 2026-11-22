"""Same-session pronunciation hypotheses. All results are development-only."""
import argparse,json
from pathlib import Path
import numpy as np
import sherpa_onnx
from .wake_samples import load_samples
from .compare_pronunciation_profiles import profiles
ROOT=Path('.tavi/models/wake')

def main():
    p=argparse.ArgumentParser();p.add_argument('collection',type=Path);a=p.parse_args();_,clips=load_samples(a.collection);out=Path('.tavi/private-wake-analysis');out.mkdir(exist_ok=True);results=[]
    configurations=[('onset_s3_p8',3,.1,8),('onset_t005_p8',2,.05,8),('onset_s3_t005_p16',3,.05,16),('onset_s4_p16',4,.1,16)]
    for name,score,threshold,paths in configurations:
        phones=profiles()['onset']
        keywords=out/f'{name}.txt';keywords.write_text('\n'.join(x+' @TAVI' for x in phones)+'\n')
        model=sherpa_onnx.KeywordSpotter(tokens=str(ROOT/'tokens.txt'),encoder=str(ROOT/'encoder-epoch-13-avg-2-chunk-8-left-64.int8.onnx'),decoder=str(ROOT/'decoder-epoch-13-avg-2-chunk-8-left-64.onnx'),joiner=str(ROOT/'joiner-epoch-13-avg-2-chunk-8-left-64.int8.onnx'),keywords_file=str(keywords),num_threads=1,keywords_score=score,keywords_threshold=threshold,max_active_paths=paths,num_trailing_blanks=1)
        rows=[]
        for clip in clips:
            stream=model.create_stream();audio=np.concatenate([np.zeros(16000,dtype=np.float32),clip['pcm'].astype(np.float32)/32768,np.zeros(16000,dtype=np.float32)]);hits=[]
            for offset in range(0,len(audio),512):
                stream.accept_waveform(16000,audio[offset:offset+512])
                while model.is_ready(stream):
                    model.decode_stream(stream)
                    if model.get_result(stream):hits.append(round(offset/16000,3));model.reset_stream(stream)
            rows.append({'number':clip['number'],'label':clip['label'],'detections':hits})
        result={'profile':name,'score':score,'threshold':threshold,'paths':paths,'positive_clips':sum(r['label']=='positive' for r in rows),'detected_positive_clips':sum(bool(r['detections']) for r in rows if r['label']=='positive'),'negative_clips':sum(r['label']=='negative' for r in rows),'false_wakes':sum(len(r['detections']) for r in rows if r['label']=='negative'),'cases':rows};results.append(result);print(json.dumps({k:v for k,v in result.items() if k!='cases'}),flush=True)
    (out/'decoder-profiles.json').write_text(json.dumps({'scope':'One development recording session; not held-out validation','results':results},indent=2)+'\n')
if __name__=='__main__':main()
