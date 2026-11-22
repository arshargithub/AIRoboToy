"""One controlled local transport/controller/guide screen; no paid inference."""
import io
import json
import subprocess
import time
import unittest
from experiments.memory.runtime import ROOT, SSD, require_ssd
from tavi.experiment_workflow import begin, audit, finish
from tavi.storage import Store


def run():
    require_ssd()
    folder, plan = begin(ROOT/'experiments/memory/recovery-protocol-v1.json', run_root=SSD/'runs/scored')
    print(json.dumps(audit(folder)), flush=True)
    cfg = json.loads((ROOT/'experiments/memory/recovery-input-v1.json').read_text())
    ledger = Store(ROOT/'.tavi/simulation/simulation.sqlite3');initial = ledger.used_micro_usd()
    stream = io.StringIO();start = time.monotonic()
    suite = unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromName(m) for m in cfg['python_modules']])
    tests = unittest.TextTestRunner(stream=stream).run(suite)
    (folder/'python-tests.txt').write_text(stream.getvalue())
    errors = []
    try:
        guide = subprocess.run(['node', cfg['javascript']], cwd=ROOT, text=True, capture_output=True,
                               timeout=max(.1, plan['limits']['maximum_wall_seconds']-(time.monotonic()-start)))
        (folder/'guide-tests.txt').write_text(guide.stdout+guide.stderr)
        guide_ok = guide.returncode == 0
    except Exception as error:
        errors.append(type(error).__name__);guide_ok = False
        (folder/'guide-tests.txt').write_text(str(error))
    if time.monotonic()-start > plan['limits']['maximum_wall_seconds']:errors.append('wall_limit')
    metrics = {'python_checks_passed': tests.testsRun-len(tests.failures)-len(tests.errors),
               'python_failures': len(tests.failures)+len(tests.errors), 'guided_javascript_passed': guide_ok,
               'collection_errors': len(errors), 'additional_api_usd': (ledger.used_micro_usd()-initial)/1e6}
    ledger.close()
    (folder/'observations.json').write_text(json.dumps({'metrics': metrics, 'elapsed_seconds': time.monotonic()-start,
       'errors': errors, 'microphone': False, 'native_engine': False, 'models': False}, indent=2)+'\n')
    sealed = finish(folder, metrics, artifacts=[folder/'observations.json', folder/'python-tests.txt', folder/'guide-tests.txt'],
                    completed=not errors, error=';'.join(errors) or None)
    report = {'run': str(folder), 'metrics': metrics, 'decision': sealed['decision'], 'audit': audit(folder),
              'critical_review': [
                  'Actual controlled subprocess/stdio lifecycle, real existing Process wrapper and queue supervisor are exercised; no actual Hindsight/Graphiti/Mem0/database/cloud cancellation proof.',
                  'Timed-out/EOF/malformed-envelope channels are retired and reject later requests, so a delayed old result cannot answer a later question on that channel. Still no per-request correlation envelope or general defence against unsolicited protocol-shaped output from a compromised worker.',
                  'Killing the owned local child does not establish remote ingestion did not finish. Working claim, ambiguous timing and cost reservation must remain until explicit reconciliation; no paid replay or automatic replacement worker.',
                  'Timeout fixture uses a warm local child, artificial5sdelay and30msdeadline with cleanup under1s assertion. Production45squery/55sprovider and existing engine deadlines unchanged; end-to-end10soutage recovery target remains open.',
                  'Acknowledged application errors are not transport failures and do not force a raw-source fallback. Identity/audience/source permission checks and terminal publication barrier remain; no synthetic memory answer is published.',
                  'Guided failure path under Node stops capture, names memory failure and permits saving partial results without independent labels or repeated speech. No actual microphone/browser/cloud/human failure acceptance or fullE6fault coverage.',
                  'Local goodbye still works after memory lookup failure. Speech synthesis failure remains a separate error; no voice or ASR model,800msendpoint, identity threshold, data destination or family enrollment change.'
              ]}
    (ROOT/'docs/evaluations/paprika_memory_worker_recovery_01.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':run()
