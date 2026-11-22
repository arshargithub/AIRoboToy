"""Zero-paid controlled orchestration screen, never household acceptance."""
import io
import json
import shutil
import time
import unittest
from pathlib import Path
from experiments.memory.runtime import ROOT, SSD, require_ssd
from tavi.experiment_workflow import begin, audit, finish, digest
from tavi.storage import Store


def run():
    require_ssd()
    folder,plan=begin(ROOT/'experiments/memory/headless-protocol-v1.json',run_root=SSD/'runs/scored')
    print(json.dumps(audit(folder)),flush=True)
    cfg=json.loads((ROOT/'experiments/memory/headless-input-v1.json').read_text())
    ledger=Store(ROOT/'.tavi/simulation/simulation.sqlite3');initial=ledger.used_micro_usd()
    control=json.loads((ROOT/cfg['development_manifest']).read_text())
    if digest(ROOT/cfg['development_log'])!=control['log_sha256']:raise ValueError('Development control log changed')
    for name in ('development_log','development_manifest'):shutil.copyfile(ROOT/cfg[name],folder/('before-'+Path(cfg[name]).name))
    start=time.monotonic();stream=io.StringIO()
    suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromName(m) for m in cfg['modules']])
    tests=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    errors=['wall_limit'] if time.monotonic()-start>plan['limits']['maximum_wall_seconds'] else []
    (folder/'tests.txt').write_text(stream.getvalue())
    metrics={'checks_passed':tests.testsRun-len(tests.failures)-len(tests.errors),
        'test_failures':len(tests.failures)+len(tests.errors),'collection_errors':len(errors),
        'pre_fix_control_failures_preserved':control['failed'],'additional_api_usd':(ledger.used_micro_usd()-initial)/1e6}
    ledger.close()
    (folder/'observations.json').write_text(json.dumps({'metrics':metrics,'errors':errors,
        'positive_identity':'explicit fictional setup, not voice inference','real_model_or_audio':False},indent=2)+'\n')
    artifacts=[folder/'tests.txt',folder/'observations.json']+list(folder.glob('before-*'))
    sealed=finish(folder,metrics,artifacts=artifacts,completed=not errors,error=';'.join(errors) or None)
    report={'run':str(folder),'metrics':metrics,'decision':sealed['decision'],'audit':audit(folder),'critical_review':[
        'Three-case unscored discovery before source repair reproduced2history leaks and1timestamp-control pass; preserved raw log and source/test hashes. The new scored run measures the repaired source, not the historical defect.',
        'Actual controller/provider/queue/background supervisor/ACK seams run with controlled transcripts, native storage, reply and voice. No hardware, acoustic response, ASR/model semantics or actual household identity performance inferred.',
        'The history authorization snapshot survives per-response cancellation. A trusted person/audience/profile/revocation change retires all prior messages and preserves only the newly accepted human input. Timestamp alone retains continuity. This conservative reset can discard otherwise-shareable history; group naturalness/E4 remains open.',
        'High/tied shadow scores remain unknown; short/overlap are explicitly unqualified test labels, not demonstrated acoustic detection. Positive cases use setup-supplied fictional identity/audience, not an enrollment/model qualification.',
        'Source capture precedes reply completion and can learn an accepted human statement even if its answer is interrupted or fails. Assistant output/unheard speech is never the source. Source revocation blocks queued audio and late completion; no derivative physical-erasure proof.',
        'An allowed new shared question may finish ingesting before its recall; its source may remain in the controlled evidence. The gate is exclusion of prior private supports, not an empty memory packet or causal semantic claim.',
        'Lock/backlog/ambiguous native and reconnect/late events are local controlled faults. Ambiguity stays unresolved, no automatic inference retry; fullE6fault matrix/soak, real model load and outage recovery timing remain unaccepted.',
        'No new recording, paid request, data destination, family threshold or live recognition change. Existing original product gates remain open.'
    ]}
    (ROOT/'docs/evaluations/paprika_pipeline_headless_01.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)


if __name__=='__main__':run()
