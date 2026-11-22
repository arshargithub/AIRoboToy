"""New vocabulary reserved for the final sequence-head test."""
import json,subprocess
from pathlib import Path
TEXTS=['Have a lovely day.','Turn the volume down.','The tavern is closed.','Tapioca pudding.','Bring a towel.','Tell Vicky hello.']
def main():
    root=Path('.tavi/wake-training/final-challenge');root.mkdir(parents=True,exist_ok=True);rows=[]
    for voice in ['Reed (English (UK))','Shelley (English (US))']:
        for i,text in enumerate(TEXTS):
            path=root/f'{voice}-{i}.wav'
            if not path.exists():
                subprocess.run(['/usr/bin/say','-v',voice,'-r','145','-o',str(path.with_suffix('.aiff')),text],check=True)
                subprocess.run(['/usr/bin/afconvert','-f','WAVE','-d','LEI16@16000','-c','1',str(path.with_suffix('.aiff')),str(path)],check=True)
            rows.append({'split':'challenge','voice':voice,'label':0,'text':text,'path':str(path)})
    (root/'corpus.json').write_text(json.dumps({'rows':rows},indent=2)+'\n');print('Final held-out vocabulary ready',flush=True)
if __name__=='__main__':main()
