"""Offline development comparison of transcription as a name gate."""
import argparse,json,os,re,time
from pathlib import Path
# These experiments accept private recordings. Model loading is local-only;
# disable hub traffic and telemetry even when the caller omits shell flags.
os.environ['HF_HUB_OFFLINE']='1'
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
import numpy as np
from faster_whisper import WhisperModel
from .wake_samples import load_samples
from .acoustics import Silero

def main():
    p=argparse.ArgumentParser();p.add_argument('collection',type=Path);p.add_argument('--model',default='.tavi/models/whisper-tiny-en');p.add_argument('--balanced-only',action='store_true');a=p.parse_args()
    model=WhisperModel(a.model,device='cpu',compute_type='int8',cpu_threads=2,local_files_only=True)
    _,clips=load_samples(a.collection);vad=Silero(Path('.tavi/models/silero_vad.onnx'),wake_backend='off');results=[]
    for prompt in (['Vocabulary: Tavi, Toby, TV, coffee, toffee, taffy, tabby.'] if a.balanced_only else [None,'Tavi is a name.']):
        rows=[]
        for clip in clips:
            vad.reset();speech=[];pcm=clip['pcm']
            for offset in range(0,len(pcm),512):
                part=pcm[offset:offset+512];part=np.pad(part,(0,512-len(part)))
                if vad.probability(part.tobytes())>=.5:speech.append(offset)
            if not speech:
                rows.append({'number':clip['number'],'label':clip['label'],'detected':False,'text':'','reason':'no_speech'});continue
            crop=pcm[max(0,speech[0]-1600):min(len(pcm),speech[-1]+512+3200)].astype(np.float32)/32768
            started=time.perf_counter();segments,_=model.transcribe(crop,language='en',beam_size=1,temperature=0,condition_on_previous_text=False,initial_prompt=prompt,vad_filter=False)
            segments=list(segments);text=' '.join(s.text for s in segments).strip();duration=(time.perf_counter()-started)*1000
            detected=bool(re.search(r'\btavi\b',text,re.I))
            rows.append({'number':clip['number'],'label':clip['label'],'detected':detected,'text':text,'decode_ms':duration,'audio_seconds':len(crop)/16000,'segments':[{'no_speech_prob':s.no_speech_prob,'avg_logprob':s.avg_logprob} for s in segments]})
        pos=[r for r in rows if r['label']=='positive'];neg=[r for r in rows if r['label']=='negative'];result={'prompt':prompt,'positive_clips':len(pos),'detected_positive_clips':sum(r['detected'] for r in pos),'negative_clips':len(neg),'false_wakes':sum(r['detected'] for r in neg),'median_decode_ms':float(np.median([r['decode_ms'] for r in rows if 'decode_ms' in r])),'cases':rows};results.append(result);print(json.dumps({k:v for k,v in result.items() if k!='cases'}),flush=True)
    out=Path('.tavi/private-wake-analysis');out.mkdir(parents=True,exist_ok=True)
    filename='local-asr-'+('balanced-' if a.balanced_only else '')+Path(a.model).name+'.json'
    (out/filename).write_text(json.dumps({'scope':'One development session; not held-out acceptance','model':a.model+' CPU int8','results':results,'api_spend_usd':0},indent=2)+'\n')
if __name__=='__main__':main()
