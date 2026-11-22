"""Historical evidence audit, not a new engine or semantic-quality experiment."""
import io
import json
from pathlib import Path
import sqlite3
import time
import unittest
from experiments.memory.runtime import ROOT,SSD,require_ssd
from experiments.memory.quality_coverage import summarize
from tavi.experiment_workflow import begin,audit,finish,digest


def spend():
    with sqlite3.connect((ROOT/'.tavi/simulation/simulation.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        return db.execute('SELECT COALESCE(SUM(COALESCE(actual,reserved)),0) FROM spending').fetchone()[0]/1e6


def run():
    require_ssd();folder,plan=begin(ROOT/'experiments/memory/coverage-audit-protocol-v1.json',run_root=SSD/'runs/scored')
    print(json.dumps(audit(folder)),flush=True);start=time.monotonic();initial=spend();errors=[];rows=[]
    cfg=json.loads((ROOT/'experiments/memory/coverage-audit-input-v1.json').read_text());corpus=json.loads((ROOT/cfg['corpus']).read_text())
    stream=io.StringIO();controls=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromName('tests.test_quality_coverage'))
    (folder/'controls.txt').write_text(stream.getvalue())
    try:
        for spec in cfg['runs']:
            source=Path(spec['folder']);old=audit(source)
            if old['state']!='finished':raise ValueError('Historical collection not sealed')
            data=json.loads((source/'observations.json').read_text());labels=json.loads((source/'reviewed-labels.json').read_text())
            result=summarize(corpus,data['queries'],labels)
            calls=json.loads((source/'calls-final.json').read_text())
            cost=sum(c.get('actual_micro_usd',c['reserved_micro_usd']) for c in calls)/1e6
            rows.append({'engine':spec['name'],'original_run':str(source),'original_outcome':old['decision'],
                'coverage':result,'published_count_reproduced':result['all_question_task_and_grounding']['correct']==spec['published_all_question_correct'],
                'historical_api_usd':cost,'historical_reservation_only_calls':sum('actual_micro_usd' not in c for c in calls)})
    except Exception as error:errors.append(type(error).__name__+': '+str(error))
    if time.monotonic()-start>plan['limits']['maximum_wall_seconds']:errors.append('wall_limit')
    metrics={'historical_runs_audited':len(rows),'explicit_reviews_accounted':sum(r['coverage']['reviewed'] for r in rows),
        'published_counts_reproduced':len(rows)==4 and all(r['published_count_reproduced'] for r in rows),
        'controlled_checks_passed':controls.testsRun-len(controls.failures)-len(controls.errors),'test_failures':len(controls.failures)+len(controls.errors),
        'collection_errors':len(errors),'historical_inputs_unchanged':all(digest(ROOT/f['path'])==f['sha256'] for f in cfg['files']),
        'additional_api_usd':spend()-initial}
    historical=sum(r['historical_api_usd'] for r in rows);budget={'spent_reserved_usd':initial,'remaining_cap_usd':25-initial,
        'one_old_all_engine_round_usd':historical,'two_more_old_rounds_usd_reference':historical*2,
        'repeat_reference_exceeds_remaining':historical*2>25-initial,
        'interpretation':'Historical configuration/call/maintenance reference only, not a currentprice forecast, proposedspend or authorization. Failedadapters should not simply be repeated. Currentbudget/allocation still enforced before each futurecall.'}
    report={'run':str(folder),'metrics':metrics,'historical_runs':rows,'budget_reference':budget,'errors':errors,
        'critical_review':[
            'No new answers or labels. Existing implementing-assistant source-paired reviews retain their original lack of reviewer independence and wording ambiguity. Reproduced counts are accounting consistency, not revalidated semantic truth.',
            'The32direct-fact subset cannot stand for all80answers. Allquestion/nonpattern/category supplemental counts make the gap visible without altering sealed historical gates or promoting any engine.',
            'Nativeprofile quality, provenance, deletion/restore, three repetitions and currentpipeline quality remain separate. Graphiti originalruntimeerror and other failedscreens are retained; no fullE5acceptance.',
            'Futureacceptance must freeze the factual/task denominator prospectively, cover identity/audience/correction/pattern claims, and preserve recall/coverage. A newhelpfulcompanion dataset must distinguish optional suggestions from inventedpersonal facts; no exactcataloguetitle scoring alone.',
            'Historicalcosts include extraction/query/profile/deletion maintenance and variableoldconditions; two-round reference is a budget warning against automaticrepeats, not a householdcost/currentprice estimate.',
            'Corpus alreadyused in model/adapter development cannot be relabelled unseen. Prepare targetedfresh current-boundary cases and a bounded costenvelope before morepaidwork. No familyaudio/profile/data destinations changed.'
        ]}
    (folder/'observations.json').write_text(json.dumps(report,indent=2)+'\n')
    record=finish(folder,metrics,artifacts=[folder/'observations.json',folder/'controls.txt'],completed=not errors,error=';'.join(errors) or None)
    report.update(decision=record['decision'],audit=audit(folder));(ROOT/'docs/evaluations/paprika_memory_coverage_audit_01.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'metrics':metrics,'outcome':record['decision']['outcome'],'budget_reference':budget}),flush=True)


if __name__=='__main__':run()
