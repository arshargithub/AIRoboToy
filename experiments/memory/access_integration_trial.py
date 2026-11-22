"""Controlled candidate/legacy integration replay only; no real native calls."""
import io
import json
import time
import unittest
from experiments.memory.runtime import ROOT,SSD,require_ssd
from experiments.memory.conversation_adapter import MemoryTextProvider
from experiments.memory.reply_boundary import qualify_context
from tavi.storage import Store
from tavi.experiment_workflow import begin,audit,finish


def run():
    require_ssd();folder,plan=begin(ROOT/'experiments/memory/access-integration-protocol-v1.json',run_root=SSD/'runs/scored')
    print(json.dumps(audit(folder)),flush=True);start=time.monotonic();errors=[]
    cfg=json.loads((ROOT/'experiments/memory/access-integration-input-v1.json').read_text())
    stream=io.StringIO();suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromName(m) for m in cfg['python_modules']])
    tests=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite);(folder/'controls.txt').write_text(stream.getvalue())
    ledger=Store();provider=MemoryTextProvider(ledger,scope=lambda:{},recall=None)
    default=provider.evidence_qualifier is qualify_context;ledger.close()
    if time.monotonic()-start>plan['limits']['maximum_wall_seconds']:errors.append('wall_limit')
    metrics={'python_checks_passed':tests.testsRun-len(tests.failures)-len(tests.errors),'test_failures':len(tests.failures)+len(tests.errors),
        'default_qualifier_unchanged':default,'collection_errors':len(errors),'additional_api_usd':0.0}
    (folder/'observations.json').write_text(json.dumps({'metrics':metrics,'errors':errors,'real_inference':False},indent=2)+'\n')
    record=finish(folder,metrics,artifacts=[folder/'controls.txt',folder/'observations.json'],completed=not errors,error=';'.join(errors) or None)
    report={'run':str(folder),'metrics':metrics,'decision':record['decision'],'audit':audit(folder),
        'critical_review':['62controlledmetadata/provider/controller/queue tests, not household/semantic/acoustic evidence. Explicitfictional setup supplies identities; no voice confidence gainsauthority.',
        'Existing15controller guards rerun underoptin plus4actualmetadata/default/factory checks; oldcallers/defaults remain unchanged. No runningUI orrobot selectsnewqualifier.',
        'Hostmetadata is advisory to replymodel and couldstillbeignored; canonicalfactfilter actually enforcesaudience. Currenttrustedhostscope/revocationepoch mustremainaccurate. No silentlistener inference or personalmemoryactivation.',
        'The earlier24casefailure and4casecomparison remainseparate sealed evidence; passingintegration cannot convert them into completeE5, fixednaturalness orfinalenginechoice.']}
    (ROOT/'docs/evaluations/paprika_memory_access_integration_01.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'metrics':metrics,'outcome':record['decision']['outcome']}),flush=True)


if __name__=='__main__':run()
