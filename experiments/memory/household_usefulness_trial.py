"""Prospective current-path memory-usefulness diagnostic; no persona changes.

Fictional accepted inputs only. One collection,12 memory replies plus4 matched
empty-evidence controls; same speaker, question, approved prompt and settings.
"""
import argparse
import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import time

from experiments.memory.access_evidence import with_access_decision
from experiments.memory.conversation_adapter import MemoryTextProvider
from experiments.memory.household_model_trial import wait_native_readiness
from experiments.memory.learning_gateway import LearningGateway
from experiments.memory.learning_queue import LearningConversation
from experiments.memory.native_text import NativeTextReference
from experiments.memory.personality_trial import BoundedLedger
from experiments.memory.runtime import ROOT,SSD,MODEL,MODEL_RATES,require_ssd
from tavi.conversation_providers import Speech
from tavi.experiment_workflow import begin,finish,audit,discover_runs,read_protocol,digest
from tavi.household_memory import HouseholdMemory
from tavi.storage import Store,APPROVED_BUDGET_MICRO_USD
from tavi.realtime_reference import charge_usage
from experiments.reliability.mac_reliability_trial import status


def validate_inputs(data):
    from experiments.memory.guarded_worker import source_rejection
    if len(data['sources'])!=16 or len(data['cases'])!=12:raise ValueError('Fixed16-source/12-case denominator')
    names=[s['alias'] for s in data['sources']]
    if len(set(names))!=16 or len({c['id'] for c in data['cases']})!=12:raise ValueError('Duplicate fixture IDs')
    if [s['at'] for s in data['sources']]!=sorted(s['at'] for s in data['sources']):raise ValueError('Chronological input required')
    for s in data['sources']:
        if source_rejection({'id':s['alias'],'speaker_id':s['speaker'],'audience_ids':s['audience'],'at':s['at'],'session':s['session'],'text':s['text']},data['people']):raise ValueError('Invalid authored source')
    if sum(c['control'] for c in data['cases'])!=4:raise ValueError('Four matched controls required')
    for c in data['cases']:
        if c['speaker'] not in c['audience'] or not set(c['audience'])<=set(data['people']):raise ValueError('Invalid query identity')
        available=data['sources'][:c['after_sources']]
        if c['after_sources'] not in (10,16) or any(s['at']>c['at'] for s in available):raise ValueError('Query cutoff does not match learned history')
        if not set(c['expected_support'])<=set(s['alias'] for s in available):raise ValueError('Future source in expected support')
        if c['control'] and set(data['control_order'][c['id']])!={'memory','empty'}:raise ValueError('Matched arm order required')
    pattern=data['cases'][0];support=[s for s in data['sources'] if s['alias'] in pattern['expected_support']]
    if len({s['session'] for s in support})!=3:raise ValueError('Pattern needs three independent sessions')


def scope_for(case,data,bank):
    # Rubric, expected sources, source-cutoff and arm identity stay out of task.
    return {'session_id':'usefulness-query','memory_epoch':bank.generation(),'task':{
        'actual_speaker_id':case['speaker'],'people':deepcopy(data['people']),
        'audience_ids':deepcopy(case['audience']),'conversation_at':case['at'],'catalogue':[]}}


async def collect(folder,plan,data,ledger):
    initial=ledger.used_micro_usd();cap=min(APPROVED_BUDGET_MICRO_USD,initial+3_000_000)
    replies=BoundedLedger(ledger,cap-initial,16);gateways=[];providers=[];references=[]
    result={'sources':{},'cases':[],'captures':[],'errors':[],'initial_micro_usd':initial,'combined_ceiling_micro_usd':cap,
            'physical_audio':False,'real_family_data':False,'calibration':False}
    began=time.monotonic();bank=None;conversation=None;fixture_store=Store();scope={}
    def remaining():
        n=plan['limits']['maximum_wall_seconds']-(time.monotonic()-began)
        if n<=0:raise TimeoutError('Whole-stage deadline')
        return n
    def save():
        result.update(additional_api_usd=(ledger.used_micro_usd()-initial)/1e6,spent_reserved_usd=ledger.used_micro_usd()/1e6,reply_requests=replies.calls)
        (folder/'observations.json').write_text(json.dumps(result,indent=2)+'\n')
    def gateway_factory(control):
        if gateways:raise ValueError('One learning gateway cycle only')
        g=LearningGateway(control,project_ceiling_micro_usd=cap,maximum_calls=64);gateways.append(g);return g
    class Acknowledge:
        async def stream_reply(self,history):yield 'Thank you for telling me.'
        async def close(self):pass
    class NoPlayback:
        async def synthesize(self,text):return Speech(b'authored-text-only',100)
        async def close(self):pass
    class RecordedReference(NativeTextReference):
        async def connect(self):
            await super().connect()
            if self.session.get('model')!='gpt-realtime-2.1' or self.session.get('reasoning')!={'effort':'minimal'} or self.session.get('max_output_tokens')!=768:
                raise ValueError('Runtime model/settings changed')
        async def send(self,kind,**fields):
            if kind=='response.create':
                self.wire=deepcopy(fields['response'])
                if hashlib.sha256(self.wire['instructions'].encode()).hexdigest()!=plan['configuration']['prompt_sha256']:raise ValueError('Approved prompt changed')
            await super().send(kind,**fields)
    def reference_factory(store):
        r=RecordedReference(store);references.append(r);return r
    async def wait_idle(n):
        while True:
            remaining();s=bank.supervisor.snapshot()
            if s['status'] in ('needs_reconciliation','owner_busy','job_bound'):raise ValueError('Learning stopped: '+s['status'])
            if bank.queue.pending()==0 and len(bank.queue.sources())==n and s['status']=='idle':return
            await asyncio.sleep(.05)
    async def query(case,arm):
        if ledger.used_micro_usd()+1_000_000>cap:raise ValueError('Unchanged reply reservation headroom exhausted; no retry or denominator reduction')
        async def empty(task):return {'sources':[],'evidence':{'facts':[]}}
        qs=scope_for(case,data,bank)
        p=MemoryTextProvider(replies,scope=lambda:{**qs,'memory_epoch':bank.generation()},recall=bank.recall if arm=='memory' else empty,
            reference_factory=reference_factory,evidence_qualifier=with_access_decision);providers.append(p)
        row={'case_id':case['id'],'arm':arm,'completed':False};result['cases'].append(row);save()
        try:
            async with asyncio.timeout(min(60,remaining())):row['text']=''.join([x async for x in p.stream_reply([{'role':'user','content':case['text']}])])
            ref=references[-1];row.update(completed=True,observation=deepcopy(p.observations[-1]),session=deepcopy(ref.session),wire=deepcopy(ref.wire))
            if not row['observation']['result']['usage_settled']:raise ValueError('Unknown usage; preserve reservation')
        finally:
            if p.observations:row['observation']=deepcopy(p.observations[-1])
            await p.close();save()
        print(json.dumps({'case':case['id'],'arm':arm,'cost_usd':result['additional_api_usd']}),flush=True)
    try:
        result['preflight']=await wait_native_readiness()
        bank=HouseholdMemory(data['people'],storage_root=folder/'fixture-household',gateway_factory=gateway_factory,source_realm='fixture')
        await bank.prepare();result['native_directory']=str(bank.directory)
        conversation=LearningConversation(fixture_store,provider=Acknowledge(),speech=NoPlayback(),context_revision=lambda:deepcopy(scope),learning_queue=bank,learning_notify=bank.notify)
        for i,s in enumerate(data['sources'],1):
            conversation.stop();scope.clear();scope.update(session_id=s['session'],task={'actual_speaker_id':s['speaker'],'people':data['people'],'audience_ids':s['audience'],'conversation_at':s['at']})
            conversation.start('authored-usefulness',online=True)
            conversation.feed('authored-usefulness',{'events':[{'type':'speech_started','utterance':i},{'type':'recognition','utterance':i,'final':True,'text':s['text'],'recognition_id':s['alias']}]})
            e=deepcopy(conversation.learning_events[-1]);result['captures'].append(e)
            if not e.get('queued') or e.get('recognition_id')!=s['alias']:raise ValueError('Actual accepted-turn capture failed')
            result['sources'][s['alias']]=e['source_id'];await wait_idle(i);save()
            print(json.dumps({'source':i,'of':16,'cost_usd':result['additional_api_usd']}),flush=True)
            if i==10:
                result['before_pattern']=bank.queue.evidence_snapshot();await query(data['cases'][0],'memory')
        await conversation.close();conversation=None
        result['completed_ingestions']=len(bank.queue.sources());sid=result['sources'][data['revoke_alias']]
        bank.queue.revoke(sid);await asyncio.to_thread(bank._send,{'op':'delete','source_id':sid})
        await wait_native_readiness(expected_paid=True)
        result['after_revoke']=bank.queue.evidence_snapshot()
        for case in data['cases'][1:]:
            for arm in data['control_order'].get(case['id'],['memory']):await query(case,arm)
        result['completed_sources_after_revoke']=len(bank.queue.sources())
    except Exception as e:result['errors'].append(type(e).__name__+': '+str(e))
    finally:
        if conversation:
            try:await conversation.close()
            except Exception as e:result['errors'].append('conversation_close:'+type(e).__name__)
        for p in providers:
            try:await p.close()
            except Exception as e:result['errors'].append('provider_close:'+type(e).__name__)
        if bank:
            try:await bank.close()
            except Exception as e:result['errors'].append('bank_close:'+type(e).__name__)
        for g in gateways:
            try:await asyncio.to_thread(g.close)
            except Exception as e:result['errors'].append('gateway_close:'+type(e).__name__)
            calls=g.folder/'gateway/calls.json';result['gateway_calls']=json.loads(calls.read_text()) if calls.exists() else []
        fixture_store.close()
        try:result['final_readiness']=await wait_native_readiness()
        except Exception as e:result['errors'].append('final_readiness:'+type(e).__name__)
        save()
    return result


def verify_configuration(row,case,data,ledger,prompt):
    result=row['observation']['result'];wire=row['wire'];payload=json.loads(wire['input'][0]['content'][0]['text'])
    session=row['session'];task=payload['task'];evidence=payload['memory_evidence']
    if (hashlib.sha256(wire['instructions'].encode()).hexdigest()!=prompt or wire['output_modalities']!=['text']
        or session['model']!='gpt-realtime-2.1' or session['reasoning']!={'effort':'minimal'} or session['max_output_tokens']!=768
        or task['actual_speaker_id']!=case['speaker'] or task['people']!=data['people'] or task['audience_ids']!=case['audience'] or task['question']!=case['text']
        or task['catalogue'] or any(k in task for k in ('required','expected_support','control','after_sources'))
        or result['status']!='completed' or result['text']!=row['text'] or not result['usage_settled']):raise ValueError('Request/model/usage binding mismatch')
    if row['arm']=='empty' and evidence['facts']:raise ValueError('Empty control contains memories')
    charge=charge_usage(result['usage']);settled=ledger.db.execute('SELECT actual FROM spending WHERE id=?',(result['reservation'],)).fetchone()
    if settled!=(charge,):raise ValueError('Reply ledger receipt mismatch')
    return True


def start():
    require_ssd();os.umask(0o077);path=ROOT/'experiments/memory/household-usefulness-protocol-v1.json';plan=read_protocol(path)
    if list((SSD/'runs/scored'/plan['experiment_id']).glob('*/run.json')):raise ValueError('One collection only; no automatic repeat')
    checks=[audit(p.parent) for p in discover_runs()]
    current=status()
    if not current['idle'] or not current['family_off'] or HouseholdMemory.qualified:raise ValueError('Leave active household session unchanged')
    data=json.loads((ROOT/plan['configuration']['input']).read_text());validate_inputs(data)
    import importlib.metadata
    env=json.loads((ROOT/'experiments/memory/learning-environment-v1.json').read_text())
    if any(importlib.metadata.version(k)!=v for k,v in env['versions'].items()):raise ValueError('Pinned dependencies changed')
    folder,plan=begin(path,run_root=SSD/'runs/scored');ledger=Store(ROOT/'.tavi/simulation/simulation.sqlite3',must_exist=True)
    print(json.dumps({'run':str(folder),'prior_valid':len(checks)}),flush=True)
    try:result=asyncio.run(collect(folder,plan,data,ledger))
    finally:ledger.close()
    print(json.dumps({'run':str(folder),'completed_replies':sum(r['completed'] for r in result['cases']),'errors':result['errors'],'additional_api_usd':result['additional_api_usd'],'awaiting':'Explicit source-paired labels before final evaluation'}),flush=True)


def seal(folder):
    folder=Path(folder);plan=read_protocol(folder/'protocol.json');data=json.loads((ROOT/plan['configuration']['input']).read_text())
    result=json.loads((folder/'observations.json').read_text());ledger=Store(ROOT/'.tavi/simulation/simulation.sqlite3',must_exist=True)
    rows=result['cases'];cases={c['id']:c for c in data['cases']};verified=[]
    try:
        for row in rows:
            if row['completed']:
                try:verified.append(verify_configuration(row,cases[row['case_id']],data,ledger,plan['configuration']['prompt_sha256']))
                except Exception as e:result['errors'].append('configuration:'+type(e).__name__+': '+str(e))
        events=result.get('gateway_calls',[])
        usage=bool(events) and all(e.get('http_status')==200 and e.get('model')==MODEL and e.get('rates_micro_usd')==list(MODEL_RATES[MODEL])
            and ledger.db.execute('SELECT actual FROM spending WHERE id=?',(e['id'],)).fetchone()==(e.get('actual_micro_usd'),)
            and digest(folder/'fixture-household/sessions'/next((folder/'fixture-household/sessions').iterdir()).name/'gateway'/f'{i:04d}-request.json')==e['request_sha256'] for i,e in enumerate(events,1))
    finally:ledger.close()
    labels=json.loads((folder/'labels.json').read_text()) if (folder/'labels.json').exists() else []
    if not result['errors'] and ({x['case_id'] for x in labels}!=set(cases) or len(labels)!=12):raise ValueError('Twelve explicit memory labels required')
    metrics={'completed_ingestions':result.get('completed_ingestions'),'completed_memory_replies':sum(r['completed'] and r['arm']=='memory' for r in rows),
             'completed_control_replies':sum(r['completed'] and r['arm']=='empty' for r in rows),'configuration_verified':len(verified),
             'learning_usage_verified':usage,'required_passes':sum(x['required'] for x in labels),'format_passes':sum(x['format'] for x in labels),
             'boundary_failures':sum(x['boundary_failure'] for x in labels),'quality_total':sum(x['quality'] for x in labels),
             'final_paid_disabled':result.get('final_readiness',{}).get('paid_enabled') is False,'additional_api_usd':result['additional_api_usd'],'collection_errors':len(result['errors'])}
    (folder/'evaluation.json').write_text(json.dumps(metrics,indent=2)+'\n')
    artifacts=[p for p in folder.rglob('*') if p.is_file() and p.name not in ('run.json','protocol.json') and not set(p.relative_to(folder).parts)&{'source','context'}]
    r=finish(folder,metrics,artifacts=artifacts,completed=not result['errors'],error='; '.join(result['errors']) or None)
    report={'date':'2026-11-10 America/Toronto','run':str(folder),'metrics':metrics,'decision':r['decision'],'audit':audit(folder),'labels':labels,
            'critical_review':['Newly authored development cases; source author/reviewer same and unmasked. No independent held-out, child or full E5 acceptance.',
                               'Matched controls hold fictional identity, question, prompt/model/settings fixed and remove memory evidence; one sample per arm and only four controls cannot establish a general causal effect.',
                               'Actual accepted-turn queue/native learning/scoped recall/current reply adapter, but no ASR/voice identity/microphone/playback or household activation.',
                               'Same exact personality, no classifier, no relevance filtering or prompt repair deployed. Original failed screens and6/8remain.',
                               'One64-call/1USDlearning gateway and16native replies share3USDstage ceiling beneath unchanged31USDglobal cap; reservations/rates/unknowns preserved.']}
    (ROOT/'docs/evaluations/paprika_household_usefulness_01.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'decision':r['decision']['outcome'],'metrics':metrics,'run':str(folder)}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['collect','seal']);p.add_argument('folder',nargs='?');a=p.parse_args()
    if a.action=='collect':start()
    else:seal(a.folder)
