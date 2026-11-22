"""Zero-paid qualification of direct listen-only routing and K acknowledgement."""
import asyncio,json,unittest
from io import StringIO
from experiments.memory.runtime import ROOT,SSD,require_ssd
from tavi.experiment_workflow import begin,audit,finish
from tavi.listen_only import listen_only
from tavi.conversation_providers import LOCAL_REPLIES
from tavi.local_speech import LocalSpeech,validate_wave
from tavi.storage import Store
async def run():
 require_ssd();folder,plan=begin(ROOT/'experiments/memory/listen-protocol-v1.json',run_root=SSD/'runs/scored');print(json.dumps(audit(folder)),flush=True)
 cases=json.loads((ROOT/'experiments/memory/listen-input-v1.json').read_text())['cases'];rows=[{**r,'actual':listen_only(r['text'])} for r in cases]
 stream=StringIO();suite=unittest.defaultTestLoader.loadTestsFromNames(['tests.test_listen_only.ListenControllerTests','tests.test_learning_queue.AcceptedLearningTests.test_listen_acknowledgement_preserves_human_source_only_when_online'])
 tests=await asyncio.to_thread(unittest.TextTestRunner(stream=stream).run,suite)
 ledger=Store(ROOT/'.tavi/simulation/simulation.sqlite3');initial=ledger.used_micro_usd();speech=LocalSpeech('kokoro-k-mlx');error=None;wav=None
 try:
  async with asyncio.timeout(45):wav=await speech.synthesize(LOCAL_REPLIES['listen']);validate_wave(wav.wav,24000);(folder/'ack.wav').write_bytes(wav.wav)
 except Exception as e:error=type(e).__name__
 finally:await speech.close()
 metrics={'explicit_commands_correct':sum(r['actual'] and r['expected'] for r in rows),'negative_controls_correct':sum(not r['actual'] and not r['expected'] for r in rows),'controller_invariants_passed':tests.testsRun-len(tests.errors)-len(tests.failures),'valid_k_acknowledgement':wav is not None,'additional_api_usd':(ledger.used_micro_usd()-initial)/1e6};ledger.close()
 result={'cases':rows,'metrics':metrics,'acknowledgement':LOCAL_REPLIES['listen'],'duration_ms':wav.duration_ms if wav else None,'error':error,'microphone':False,'physical_playback':False};(folder/'observations.json').write_text(json.dumps(result,indent=2)+'\n')
 art=[folder/'observations.json']+([folder/'ack.wav'] if wav else [])
 sealed=finish(folder,metrics,artifacts=art,completed=error is None,error=error)
 report={'run':str(folder),**result,'decision':sealed['decision'],'audit':audit(folder),'critical_review':['40authored development forms test conservative lexical boundaries, not general English intent understanding or held-out ASR. Unrecognized paraphrases still use the ordinary model path.','Actual whole/sentence controllers require engagement, avoid reply inference for supported listen-only commands and allow later user-led ordinary questions. Stops/goodbye/negated listening/reports/quotes retain ordinary handling.','Listen-only statements can contain significant events. Opt-in online learning retains the HUMAN source with its current timestamp; acknowledgements are not learned. Offline mode cannot dispatch memory extraction.','K acknowledgement is a valid24kHzPCM WAV with unchanged provisional voice. No acoustic listening/naturalness, microphone, child or E3acceptance inferred.','The failed native-only pattern case remains failed and immutable. This controller boundary prevents that exact class of output for supported explicit commands; it does not claim the native model never gives unwanted advice.']}
 (ROOT/'docs/evaluations/paprika_listen_only_01.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'metrics':metrics,'decision':sealed['decision']['outcome'],'duration_ms':result['duration_ms']}),flush=True)
if __name__=='__main__':asyncio.run(run())
