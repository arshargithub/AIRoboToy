"""Public-demo CPU/transport sanity screen, never household speaker acceptance."""
import json,time,wave,unittest
from io import StringIO
from pathlib import Path
import numpy as np
from experiments.memory.runtime import ROOT,SSD
from tavi.experiment_workflow import begin,audit,finish
from tavi.speaker_process import SpeakerProcess
from tavi.storage import Store

def run():
 folder,plan=begin(ROOT/'experiments/speaker-id/component-protocol-v1.json',run_root=SSD/'runs/scored');print(json.dumps(audit(folder)),flush=True)
 rows=json.loads((ROOT/'experiments/speaker-id/public-fixtures.json').read_text())['files'];worker=SpeakerProcess();ledger=Store(ROOT/'.tavi/simulation/simulation.sqlite3');initial=ledger.used_micro_usd();result={'rows':[],'errors':[],'household_audio':False,'physical_playback':False};start=time.monotonic()
 try:
  t=time.monotonic();worker.prepare();result['startup_ms']=(time.monotonic()-t)*1000
  for row in rows:
   with wave.open(row['path']) as w:
    if (w.getnchannels(),w.getsampwidth(),w.getframerate())!=(1,2,16000):raise ValueError('Public WAV format')
    pcm=w.readframes(min(w.getnframes(),128000))
   t=time.monotonic();out=worker.encode(pcm);result['rows'].append({'path':row['path'],'speaker':row['speaker'],'ms':(time.monotonic()-t)*1000,'result':out})
  rejected=0
  for data in [b'\0'*16000,b'\0'*256000]:
   try:worker.encode(data)
   except ValueError:rejected+=1
  result['impaired_controls_rejected']=rejected
 except Exception as e:result['errors'].append(type(e).__name__+': '+str(e))
 finally:worker.close()
 vectors=[np.array(r['result']['embedding']) for r in result['rows']];same=float(vectors[0]@vectors[1]) if len(vectors)==3 else None;different=max(float(vectors[0]@vectors[2]),float(vectors[1]@vectors[2])) if len(vectors)==3 else None
 stream=StringIO();suite=unittest.defaultTestLoader.loadTestsFromName('tests.test_speaker_profile');tests=unittest.TextTestRunner(stream=stream).run(suite)
 metrics={'public_clips_completed':len(vectors),'finite_normalized_512d':len(vectors)==3 and all(v.shape==(512,) and np.isfinite(v).all() and abs(np.linalg.norm(v)-1)<.0001 for v in vectors),'same_different_score_gap':same-different if same is not None else None,'startup_ms':result.get('startup_ms'),'maximum_encode_ms':max((r['ms'] for r in result['rows']),default=None),'impaired_controls_rejected':result.get('impaired_controls_rejected',0),'storage_invariants_passed':tests.testsRun-len(tests.errors)-len(tests.failures),'collection_errors':len(result['errors']),'additional_api_usd':(ledger.used_micro_usd()-initial)/1e6}
 ledger.close();result.update(metrics=metrics,same_demo_score=same,max_different_demo_score=different,wall_seconds=time.monotonic()-start,threshold_selected=False,recognition_enabled=False)
 (folder/'observations.json').write_text(json.dumps(result,indent=2)+'\n');sealed=finish(folder,metrics,artifacts=[folder/'observations.json'],completed=not result['errors'],error='; '.join(result['errors']) or None)
 report={'run':str(folder),'metrics':metrics,'same_demo_score':same,'max_different_demo_score':different,'decision':sealed['decision'],'audit':audit(folder),'critical_review':['Three upstream demonstration clips from two speakers, used only for API/shape/normalization/same-versus-different sanity. No household accuracy, unknown rejection rate, EER, overlap or child acceptance inferred.','One pretrained CAM++ English/VoxCeleb ONNX, official30MBconverted asset, pinnedSHA256. ExistingSherpa2.0.1/NumPy2.4.2/ORT1.24.2, CPU2threads plus localSilero1thread. Not a comparison with legacy SpeechBrain ECAPA or a Pi benchmark.','Public demo gap is not a threshold. Upstream modelcard example threshold0.39 is not adopted. Candidate profiles never authorize personal memory; held-out sessions and device-matched other/unknown voices remain necessary.','Silero>=.5,>=2voicedseconds/RMS>=.003/clipping<=3percent are collection-quality screens, not speaker verification. Short/silence rejected; VAD does not prove one speaker or reject overlap. Adult-alone consent and later E4 still required.','Native work runs in an owned offline subprocess with bounded startup/request and kill-on-timeout. No family recordings, microphone, cloud or paid calls.','Adult-trained speaker models may not generalize to children; ChildAugment2024 provides a relevant ECAPA-based example. Do not transfer its gains or the demo scores to this different CAM++ model or the household.']}
 (ROOT/'docs/evaluations/paprika_speaker_component_01.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
if __name__=='__main__':run()
