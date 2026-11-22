"""Fresh synthetic voices selected after rejecting the first head; no tuning."""
import hashlib,json,subprocess
from pathlib import Path
from .train_custom_wake import POS,NEG

def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--final',action='store_true');args=parser.parse_args()
    root=Path('.tavi/wake-training/'+('final-test' if args.final else 'fresh-test'));root.mkdir(parents=True,exist_ok=True);rows=[]
    voices=['Reed (English (UK))','Shelley (English (US))'] if args.final else ['Eddy (English (US))','Flo (English (UK))']
    for voice in voices:
        for label,texts in [(1,POS),(0,NEG)]:
            for rate in ([120,150,180] if label else [145]):
                for i,text in enumerate(texts):
                    path=root/f'{voice}-{label}-{rate}-{i}.wav'
                    if not path.exists():
                        subprocess.run(['/usr/bin/say','-v',voice,'-r',str(rate),'-o',str(path.with_suffix('.aiff')),text],check=True)
                        subprocess.run(['/usr/bin/afconvert','-f','WAVE','-d','LEI16@16000','-c','1',str(path.with_suffix('.aiff')),str(path)],check=True)
                    rows.append({'split':'test','voice':voice,'label':label,'text':text,'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        print('Fresh voice generated:',voice,flush=True)
    (root/'corpus.json').write_text(json.dumps({'rows':rows,'scope':'Held-out synthetic voices; not family voices'},indent=2)+'\n')

if __name__=='__main__':main()
