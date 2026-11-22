"""Frozen microphone-free preview qualification; all examples are fictional."""
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
    folder, plan = begin(ROOT/'experiments/speaker-id/adventure-preview-protocol-v1.json', run_root=SSD/'runs/scored')
    print(json.dumps(audit(folder)), flush=True)
    cfg = json.loads((ROOT/'experiments/speaker-id/adventure-preview-input-v1.json').read_text())
    ledger = Store(ROOT/'.tavi/simulation/simulation.sqlite3');initial = ledger.used_micro_usd()
    start = time.monotonic();errors = [];count = 0;js_fail = 0
    try:
        js = subprocess.run(['node', cfg['javascript']], cwd=ROOT, text=True, capture_output=True, timeout=20)
        (folder/'javascript.txt').write_text(js.stdout+js.stderr)
        if js.returncode == 0 and f"{cfg['javascript_invariants']} state/store/actual-UI invariants pass" in js.stdout:count = cfg['javascript_invariants']
        else:js_fail = 1
    except Exception as error:
        errors.append(type(error).__name__);(folder/'javascript.txt').write_text(str(error))
    stream = io.StringIO()
    tests = unittest.TextTestRunner(stream=stream).run(unittest.defaultTestLoader.loadTestsFromName(cfg['http_module']))
    (folder/'http-tests.txt').write_text(stream.getvalue())
    if time.monotonic()-start > plan['limits']['maximum_wall_seconds']:errors.append('wall_limit')
    metrics = {'javascript_invariants_passed': count, 'http_tests_passed': tests.testsRun-len(tests.errors)-len(tests.failures),
               'test_failures': js_fail+len(tests.errors)+len(tests.failures), 'collection_errors': len(errors),
               'additional_api_usd': (ledger.used_micro_usd()-initial)/1e6}
    ledger.close()
    (folder/'observations.json').write_text(json.dumps({'metrics': metrics, 'errors': errors,
        'real_audio': False, 'real_profiles': False, 'human_acceptance': False}, indent=2)+'\n')
    sealed = finish(folder, metrics, artifacts=[folder/'observations.json', folder/'javascript.txt', folder/'http-tests.txt'],
                    completed=not errors, error=';'.join(errors) or None)
    report = {'run': str(folder), 'metrics': metrics, 'decision': sealed['decision'], 'audit': audit(folder), 'critical_review': [
        'All outcomes and examples are fictional. No acoustic quality, identity, overlap rejection, child enjoyment or E4 acceptance can be inferred from this screen.',
        'Six story turns produce four eligible pretend examples; two fresh prompts can complete six reviewed examples. Every turn advances, independently of technical acceptance. Parent can exclude otherwise eligible examples; rejected short/noisy results cannot be promoted.',
        'State/store/actual UI JavaScript tests exercise pause/reload/checking, finishing-and-continuing, duplicate/stale receipts, parent rejection,12turn bound, corrupt/quota recovery, lost-save acknowledgement and preserved separate previews.',
        'Browser storage contains fictional state only; this is not the future biometric source of truth or a concurrent multi-writer database. Sequential stale revisions are refused; a truly simultaneous cross-tab read/write race is not qualified. Clearing browser data loses its saved previews.',
        'This preview caps twelve total turns, not a proven three-minute child session. Multi-sitting real profile continuation beyond that cap, capture quality, spoken prompts, parent/child consent and real local profile persistence remain separate work.',
        'The server serves allowlisted assets/health only and rejects mutation requests. Permissions/CSP and forbidden capability traps support the microphone-free boundary; the agent supplied no microphone/recording consent.',
        'No new models, recordings, paid calls or changes to the parked adult enrollment flow. Existing project acceptance gates and family identity remain open.'
    ]}
    (ROOT/'docs/evaluations/paprika_child_adventure_preview_01.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':run()
