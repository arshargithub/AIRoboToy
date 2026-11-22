"""Prospective repair checks on preserved fictional pilot evidence/copy only."""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import time

from experiments.memory.runtime import SSD,ROOT,require_ssd
from experiments.memory.context_envelope import pack
from experiments.memory.pilot import Process,answer
from tavi.experiment_workflow import begin,audit,digest


def run(protocol):
    require_ssd()
    os.environ['TIKTOKEN_CACHE_DIR']=str(SSD/'models/tiktoken')
    import tiktoken
    encoding=tiktoken.get_encoding('o200k_base')
    folder,plan=begin(protocol,run_root=SSD/'runs/scored')
    broker=json.loads((SSD/'private-config/broker.json').read_text())
    source=Path(plan['configuration']['pilot_directory'])
    original=json.loads((source/'observations.json').read_text())
    fixtures=json.loads((ROOT/'experiments/memory/pilot-fixtures.json').read_text())
    packed=[];paired=[];native_check={};error=None
    logs=folder/'logs';logs.mkdir()
    worker=None
    def deadline_expired(*args):raise TimeoutError('Focused check exceeded its1200-second bound')
    previous=signal.signal(signal.SIGALRM,deadline_expired)
    signal.alarm(1200)
    try:
        for row in original['queries']:
            question=row['question'];after=next(i for i,e in enumerate(fixtures['episodes']) if e['id']==question['after'])
            result=pack(row['engine'],row['retrieval']['result']['native_context'],
                fixtures['episodes'][:after+1],question['audience_ids'],encoding)
            packed.append({'engine':row['engine'],'question_id':question['id'],**result})
        # Same stored native retrieval, same model/prompt, old/new context only.
        # Reverse order for the second case to reduce a simple order confound.
        for index,(engine,qid) in enumerate([('hindsight','q06'),('graphiti','q07')]):
            row=next(q for q in original['queries'] if q['engine']==engine and q['question']['id']==qid)
            new=next(q for q in packed if q['engine']==engine and q['question_id']==qid)
            contexts={'control':row['context'],'candidate':new['context']}
            for mode in (['control','candidate'] if index==0 else ['candidate','control']):
                response=answer(engine,row['question'],fixtures['people'],contexts[mode],broker)
                paired.append({'engine':engine,'question_id':qid,'mode':mode,'answer':response,
                    'context_sha256':__import__('hashlib').sha256(contexts[mode].encode()).hexdigest()})
                print(json.dumps({'paired':engine+'/'+qid,'mode':mode}),flush=True)
        # Preserve the failed trial's actual database; copy only the closed RDB
        # and SQLite files. Never copy .settings (which names the old socket).
        old=SSD/'databases'/source.parent.name/(source.name+'-graphiti')
        expected=plan['configuration']['graphiti_database_sha256']
        for name,sha in expected.items():
            if digest(old/name)!=sha:raise ValueError('Original Graphiti database changed before copy')
        target=folder/'database'/old.name;target.mkdir(parents=True)
        for name in expected:shutil.copy2(old/name,target/name)
        native_check['original_hashes_before']=expected
        worker=Process('graphiti',target,logs)
        native_check['initialize']=worker.send({'op':'initialize'},timeout=120)
        native_check['delete']=worker.send({'op':'delete','source_id':'e15'})
        worker.stop();worker=Process('graphiti',target,logs)
        native_check['restart']=worker.send({'op':'initialize'},timeout=120)
        native_check['retrieval']=worker.send({'op':'query','people':fixtures['people'],'question':{
            'id':'delete-check','asker':'p1','audience_ids':['p1','p2','p3','p4'],
            'text':'What award did Finley win at the football match?','at':'2026-02-05T16:02:00Z'}})
        native_check['original_hashes_after']={name:digest(old/name) for name in expected}
    except Exception as exc:
        error=type(exc).__name__+': '+str(exc)
    finally:
        signal.alarm(0);signal.signal(signal.SIGALRM,previous)
        if worker:worker.stop()
        import httpx
        response=httpx.post(broker['base_url']+'/control/disable-paid',
            headers={'Authorization':'Bearer '+broker['token']},timeout=100)
        response.raise_for_status()
        (folder/'calls-final.json').write_text(json.dumps(response.json()['calls'],indent=2))
    result={'repacked':packed,'paired_answers':paired,'native_delete':native_check,'error':error}
    (folder/'observations.json').write_text(json.dumps(result,indent=2)+'\n')
    # Freeze/finish only after the explicit engineering semantic review. No
    # keyword match is silently promoted to an independent quality label.
    print(json.dumps({'run':str(folder),'awaiting':'assistant critical review and finish',
                      'error':error,'audit':audit(folder)}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('protocol');run(parser.parse_args().protocol)
