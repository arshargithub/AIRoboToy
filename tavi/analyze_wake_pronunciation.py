"""Local phonetic diagnostic, never an acceptance test or cloud transcription."""
import argparse,json
from pathlib import Path
import numpy as np
import sherpa_onnx
from .wake_samples import load_samples

ROOT=Path('.tavi/models/wake')
def main():
 p=argparse.ArgumentParser();p.add_argument('collection',type=Path);args=p.parse_args();_,clips=load_samples(args.collection)
 recognizer=sherpa_onnx.OnlineRecognizer.from_transducer(tokens=str(ROOT/'tokens.txt'),encoder=str(ROOT/'encoder-epoch-13-avg-2-chunk-8-left-64.int8.onnx'),decoder=str(ROOT/'decoder-epoch-13-avg-2-chunk-8-left-64.onnx'),joiner=str(ROOT/'joiner-epoch-13-avg-2-chunk-8-left-64.int8.onnx'),num_threads=1)
 rows=[]
 for clip in clips:
  stream=recognizer.create_stream();audio=clip['pcm'].astype(np.float32)/32768;audio=np.concatenate([audio,np.zeros(16000,dtype=np.float32)])
  for i in range(0,len(audio),512):
   stream.accept_waveform(16000,audio[i:i+512])
   while recognizer.is_ready(stream):recognizer.decode_stream(stream)
  result=recognizer.get_result(stream);rows.append({'number':clip['number'],'label':clip['label'],'phonetic_output':result})
  if clip['label']=='positive':print(clip['number'],result,flush=True)
 out=Path('.tavi/private-wake-analysis');out.mkdir(exist_ok=True);(out/'phonetic-result.json').write_text(json.dumps({'scope':'Same-session local diagnostic; not reliable transcription','cases':rows},indent=2)+'\n')
if __name__=='__main__':main()
