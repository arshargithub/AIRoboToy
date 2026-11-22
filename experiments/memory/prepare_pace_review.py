"""Saved measured readiness plus real K chunks; no regenerated speech.

Silence is a replay of software-ready timings, not measured acoustic latency.
Accelerated ACKs mean chunk readiness is optimistic; no live timing claim.
"""
import hashlib,json,wave
from pathlib import Path
from experiments.memory.runtime import ROOT,SSD,require_ssd

def main():
 require_ssd();run=SSD/'runs/scored/MEMORY-COMBINED-01/20261105T232019482331Z'
 d=json.loads((run/'observations.json').read_text());out=SSD/'previews/conversation-pace-v1';out.mkdir(exist_ok=False)
 descriptions={
 'ordinary1':('A quick question','No personal memory is needed to answer this. The current system still performs its permitted lookup.','Paprika, how many sides does a triangle have?'),
 'gift1':('A personal gift idea','In this fictional household, Theo already built Gear Buggy. He enjoys visible gears and wants to try a solar model. Sun Gear fits those interests.','Paprika, what would be a good new present for Theo?'),
 'book1':('The slower first reply','In this fictional household, Nora liked a funny, gentle mystery and wants a new one. Maple Mystery fits. This was the first memory question after the query client started; its delay was longer.','Paprika, could you suggest a new mystery for me to read?')}
 examples=[]
 for key,(title,situation,question) in descriptions.items():
  row=next(r for r in d['cases'] if r['id']==key);frames=bytearray();trace=[]
  for part in row['chunks']:
   ready=round(part['ready_ms']/1000*24000);current=len(frames)//2
   frames.extend(bytes(max(0,ready-current)*2));trace.append({'sequence':part['sequence'],'start_frame':len(frames)//2,'source_sha256':part['sha256']})
   path=Path(part['audio_path']);assert hashlib.sha256(path.read_bytes()).hexdigest()==part['sha256']
   with wave.open(str(path),'rb') as w:
    assert (w.getframerate(),w.getnchannels(),w.getsampwidth())==(24000,1,2)
    frames.extend(w.readframes(w.getnframes()))
  dest=out/(key+'.wav')
  with wave.open(str(dest),'wb') as w:w.setparams((1,2,24000,0,'NONE','not compressed'));w.writeframes(frames)
  examples.append({'id':key,'title':title,'situation':situation,'question':question,'text':row['text'],'wait_ms':row['first_audio_ms'],'chunk_trace':trace,'variants':[{'id':'replay','duration_ms':len(frames)/48,'audio_path':str(dest),'audio_sha256':hashlib.sha256(dest.read_bytes()).hexdigest()}]})
 examples.append({'id':'next_step','title':'Choose what matters next','decision':True,'variants':[]})
 manifest={'kind':'conversation_pace_decision','review_type':'pace','source_run':str(run),'source_sha256':hashlib.sha256((run/'observations.json').read_bytes()).hexdigest(),'scope':'Owner judgment of optimistic measured software-ready delay with actual saved K, not live acoustic or acceptance evidence. No mic or inference. A limited pilot choice explicitly leaves3s ordinary/5s memory targets open.','examples':examples}
 (ROOT/'experiments/memory/conversation-pace-preview-v1.json').write_text(json.dumps(manifest,indent=2)+'\n')
 print(json.dumps({'examples':3,'microphone':False,'paid_requests':0,'output':str(out)}))
if __name__=='__main__':main()
