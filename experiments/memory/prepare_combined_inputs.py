"""Prepare fictional synthetic input WAVs locally; not an ASR accuracy run."""
import asyncio,audioop,hashlib,json,wave
from io import BytesIO
from pathlib import Path
from experiments.memory.runtime import ROOT,SSD,require_ssd
from tavi.local_speech import LocalSpeech

async def run():
 require_ssd();root=SSD/'previews/combined-input-v1';root.mkdir(exist_ok=False)
 fixture=json.loads((ROOT/'experiments/memory/decision-v2-input.json').read_text())
 book=next(x['catalogue'] for x in fixture['cases'] if x['id']=='n01');gift=next(x['catalogue'] for x in fixture['cases'] if x['id']=='n02')
 specs=[
 ('book1','book','a','memory','Paprika, could you suggest a new mystery for me to read?',book,'Maple Mystery, not already-read Cedar Cases; supported funny/gentle/short features.'),
 ('book2','book','a','memory','What makes that one a good match for me?',book,'Explain the previous recommendation using Nora preferences, preserve reference without name.'),
 ('comfort1','comfort','c','memory','Paprika, I feel tense. What could help me unwind?',[],'Acknowledge; optional reported quiet folk music, not loud concert, no assumed cause.'),
 ('comfort2','comfort','c','memory','No music today. Could we do something else?',[],'Respect refusal; optional current paper folding or gentle reading, no promised calming effect.'),
 ('gift1','gift','a','memory','Paprika, what would be a good new present for Theo?',gift,'Sun Gear uses solar and visible gears; Gear Buggy already owned and completed.'),
 ('gift2','gift','a','memory','Why would he enjoy that?',gift,'Resolve Theo/previous Sun Gear; reported interest in visible gears and solar models, no invented traits.'),
 ('ordinary1','ordinary','a','ordinary','Paprika, how many sides does a triangle have?',[],'Three; no irrelevant personal memory.'),
 ('ordinary2','ordinary','a','ordinary','Tell me a tiny story about a turtle.',[],'Brief fictional turtle story, no invented personal memories or assertion of real observation.')]
 voice=LocalSpeech('kokoro-k-mlx');rows=[];files=[]
 try:
  await voice.prepare()
  for id,session,speaker,category,text,catalogue,oracle in specs:
   audio=await voice.synthesize(text)
   with wave.open(BytesIO(audio.wav),'rb') as w:pcm=w.readframes(w.getnframes())
   pcm,_=audioop.ratecv(pcm,2,1,24000,16000,None)
   pcm=b'\0'*5120+pcm+b'\0'*10240
   path=root/(id+'.wav')
   with wave.open(str(path),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(pcm)
   sha=hashlib.sha256(path.read_bytes()).hexdigest();files.append({'path':str(path),'sha256':sha})
   rows.append({'id':id,'session':session,'speaker':speaker,'category':category,'text':text,'catalogue':catalogue,'oracle':oracle,'path':str(path),'sha256':sha,'duration_seconds':len(pcm)/32000})
 finally:await voice.close()
 (ROOT/'experiments/memory/combined-input-v1.json').write_text(json.dumps({'kind':'fictional_K_synthetic_only','cases':rows},indent=2)+'\n')
 models=json.loads((ROOT/'tavi/asr_mlx_manifest.json').read_text())
 for m in models['models']:
  if m['id']=='turbo':
   for name,row in m['files'].items():files.append({'path':str(ROOT/m['path']/name),'sha256':row['sha256']})
 files+=json.loads((ROOT/'experiments/memory/voice-queue-manifest.json').read_text())['files']
 (ROOT/'experiments/memory/combined-manifest-v1.json').write_text(json.dumps({'files':files},indent=2)+'\n')
 print(json.dumps({'synthetic_clips':len(rows),'total_seconds':sum(x['duration_seconds'] for x in rows)}))

if __name__=='__main__':asyncio.run(run())
