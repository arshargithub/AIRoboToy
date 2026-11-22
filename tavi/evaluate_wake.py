"""Synthetic development comparison. No family recordings or API calls."""
import json
from pathlib import Path
import subprocess
import wave
from .wake import SherpaWake

def main():
    root=Path('.tavi/audio/wake-comparison');root.mkdir(parents=True,exist_ok=True)
    cases=[]
    texts={'positive':'Tah vee. Hello Tah vee. Tah vee, tell me a story.',
           'negative':'Coffee and toffee. Turn on the TV. Toby likes taffy. That view is lovely. Tell me a story. Have a nice day.'}
    for voice in ('Samantha','Daniel','Karen'):
        for rate in (130,175):
            for label,text in texts.items():
                path=root/f'{voice}-{rate}-{label}.wav'
                if not path.exists():
                    aiff=path.with_suffix('.aiff')
                    subprocess.run(['/usr/bin/say','-v',voice,'-r',str(rate),'-o',str(aiff),text],check=True)
                    subprocess.run(['/usr/bin/afconvert','-f','WAVE','-d','LEI16@16000','-c','1',str(aiff),str(path)],check=True)
                cases.append((voice,rate,label,path))
    configurations=[dict(precision='int8',threshold=.1,score=2,variants=False),dict(precision='fp32',threshold=.1,score=2,variants=True),dict(precision='fp32',threshold=.08,score=2.5,variants=True)]
    results=[]
    for config in configurations:
        model=SherpaWake(**config);rows=[]
        for voice,rate,label,path in cases:
            model.reset();count=0
            with wave.open(str(path),'rb') as wav:
                while pcm:=wav.readframes(512):
                    count+=bool(model.feed(pcm+bytes(1024-len(pcm))))
            for _ in range(32):count+=bool(model.feed(bytes(1024)))
            rows.append(dict(voice=voice,rate=rate,label=label,detections=count))
        result={'config':config,'positive_detections':sum(r['detections'] for r in rows if r['label']=='positive'),'positive_opportunities':18,'negative_detections':sum(r['detections'] for r in rows if r['label']=='negative'),'cases':rows}
        results.append(result);print(json.dumps({k:v for k,v in result.items() if k!='cases'}),flush=True)
    (root/'results.json').write_text(json.dumps({'scope':'Synthetic development only; not family acceptance','results':results},indent=2)+'\n')

if __name__=='__main__':main()
