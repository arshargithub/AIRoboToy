"""Additional synthetic negative phrases excluded from training/selection."""
import json,subprocess
from pathlib import Path
TEXTS=['Have we met?','Take the TV remote.','Tall trees.','The tabby cat.','Tuba music.','Please talk to me.']
def main():
    root=Path('.tavi/wake-training/challenge');root.mkdir(parents=True,exist_ok=True);rows=[]
    for voice in ['Tessa','Kathy']:
        for i,text in enumerate(TEXTS):
            path=root/f'{voice}-{i}.wav'
            if not path.exists():
                subprocess.run(['/usr/bin/say','-v',voice,'-r','145','-o',str(path.with_suffix('.aiff')),text],check=True)
                subprocess.run(['/usr/bin/afconvert','-f','WAVE','-d','LEI16@16000','-c','1',str(path.with_suffix('.aiff')),str(path)],check=True)
            rows.append({'split':'challenge','voice':voice,'label':0,'text':text,'path':str(path)})
    (root/'corpus.json').write_text(json.dumps({'rows':rows},indent=2)+'\n');print('Novel negative challenge ready',flush=True)
if __name__=='__main__':main()
