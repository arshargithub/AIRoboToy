"""One approved isolated actual-memory check; no microphone/calibration/playback.

Learning, recall, source qualification and replies use their actual adapters.
Only identity/audience and accepted speech are authored fixture inputs.
"""
import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import urllib.request

from experiments.memory.access_evidence import with_access_decision
from experiments.memory.conversation_adapter import MemoryTextProvider
from experiments.memory.learning_gateway import LearningGateway
from experiments.memory.learning_queue import LearningConversation
from experiments.memory.native_text import NativeTextReference
from experiments.memory.personality_trial import BoundedLedger
from experiments.memory.runtime import ROOT,SSD,require_ssd
from tavi.conversation_providers import Speech
from tavi.experiment_workflow import begin,audit,discover_runs,read_protocol,digest
from tavi.household_memory import HouseholdMemory
from tavi.memory_projection import projection_report
from tavi.storage import Store,APPROVED_BUDGET_MICRO_USD


class NativeServicesBusy(ValueError):pass


def native_readiness(*,expected_paid=False):
    """Metadata only; never operate on a nonquiescent shared native service."""
    import psycopg2
    with urllib.request.urlopen('http://127.0.0.1:8790/health',timeout=3) as r:health=json.load(r)
    if health['paid_enabled']!=expected_paid:raise ValueError('Unexpected inference gateway state')
    with urllib.request.urlopen('http://127.0.0.1:8791/health',timeout=3) as r:r.read()
    c=psycopg2.connect(json.loads((SSD/'private-config/postgres.json').read_text())['uri'])
    try:
        with c.cursor() as q:
            q.execute("SELECT count(*) FROM async_operations WHERE status IN ('pending','processing')");pending=q.fetchone()[0]
            queues={}
            for table in ['entity_maintenance_queue','graph_maintenance_queue']:
                q.execute('SELECT count(*) FROM '+table);queues[table]=q.fetchone()[0]
    finally:c.close()
    if pending or any(queues.values()):raise NativeServicesBusy('Shared native jobs are not quiescent')
    return {'paid_enabled':health['paid_enabled'],'pending_native_jobs':pending,'maintenance_counts':queues}


async def wait_native_readiness(*,expected_paid=False,maximum_seconds=30):
    deadline=time.monotonic()+maximum_seconds
    while True:
        try:return await asyncio.to_thread(native_readiness,expected_paid=expected_paid)
        except NativeServicesBusy:
            if time.monotonic()>=deadline:raise TimeoutError('Native maintenance did not drain within its bound')
            await asyncio.sleep(.1)


def validate_inputs(data):
    from experiments.memory.guarded_worker import source_rejection
    if len(data['sources'])!=8 or len(data['cases'])!=4:raise ValueError('Fixed8source/4replydenominator required')
    if len({s['alias'] for s in data['sources']})!=8 or len({q['id'] for q in data['cases']})!=4:raise ValueError('Duplicate fixture IDs')
    for s in data['sources']:
        if source_rejection({'id':s['alias'],'session':'fixture-'+s['alias'],'speaker_id':s['speaker'],
            'audience_ids':s['audience'],'at':s['at'],'text':s['text']},data['people']):raise ValueError('Unqualified authored source')
    for c in data['cases']:
        if c['speaker'] not in c['audience'] or not set(c['audience'])<=set(data['people']):raise ValueError('Invalid fixture audience')


async def collect(folder,plan,data,ledger):
    initial=ledger.used_micro_usd();cap=min(APPROVED_BUDGET_MICRO_USD,31000000,initial+3750000)
    replies=BoundedLedger(ledger,cap-initial,4);gateways=[];references=[];providers=[]
    result={'sources':{},'captures':[],'cases':[],'errors':[],'initial_micro_usd':initial,'combined_ceiling_micro_usd':cap,
            'calibration':False,'real_household_data':False,'physical_playback':False}
    deadline=time.monotonic()+plan['limits']['maximum_wall_seconds']
    def remaining():
        v=deadline-time.monotonic()
        if v<=0:raise TimeoutError('Overall memory check deadline')
        return v
    def save():
        result.update(additional_api_usd=(ledger.used_micro_usd()-initial)/1e6,
            spent_reserved_usd=ledger.used_micro_usd()/1e6,reply_requests=replies.calls,gateway_cycles=len(gateways))
        (folder/'observations.json').write_text(json.dumps(result,indent=2)+'\n')
    def gateway_factory(control):
        if len(gateways)>=2:raise ValueError('Gateway cycle bound')
        gateway=LearningGateway(control,project_ceiling_micro_usd=cap);gateways.append(gateway);return gateway
    bank=HouseholdMemory(data['people'],storage_root=folder/'fixture-household',gateway_factory=gateway_factory,source_realm='fixture')
    fixture_store=Store();conversation=None;scope={}
    class Acknowledge:
        async def stream_reply(self,history):yield 'Thank you for telling me.'
        async def close(self):pass
    class NoPlayback:
        async def synthesize(self,text):return Speech(b'not-played-fixture',100)
        async def close(self):pass
    class RecordingReference(NativeTextReference):
        async def connect(self):
            await super().connect()
            if (self.session.get('model')!='gpt-realtime-2.1' or self.session.get('reasoning')!={'effort':'minimal'}
                    or self.session.get('max_output_tokens')!=768 or self.session.get('tools')!=[]
                    or self.session.get('tool_choice')!='none'):
                raise ValueError('Reply session configuration changed')
        async def send(self,kind,**fields):
            if kind=='response.create':
                self.wire=deepcopy(fields['response'])
                if hashlib.sha256(self.wire['instructions'].encode()).hexdigest()!=plan['configuration']['prompt_sha256']:
                    raise ValueError('Approved reply prompt changed')
            await super().send(kind,**fields)
    def reference_factory(store):
        ref=RecordingReference(store);references.append(ref);return ref
    async def wait_idle(expected):
        while True:
            remaining();state=bank.supervisor.snapshot()
            if state['status'] in ('needs_reconciliation','owner_busy','job_bound'):raise ValueError('Learning stopped: '+state['status'])
            if bank.queue.pending()==0 and state['status']=='idle' and len(bank.queue.sources())==expected:return
            await asyncio.sleep(.05)
    try:
        await bank.prepare();result['native_directory']=str(bank.directory)
        result['namespace_manifest']=json.loads((folder/'fixture-household/native-generation.json').read_text());save()
        conversation=LearningConversation(fixture_store,provider=Acknowledge(),speech=NoPlayback(),
            context_revision=lambda:deepcopy(scope),learning_queue=bank,learning_notify=bank.notify)
        for i,source in enumerate(data['sources'],1):
            remaining();conversation.stop();scope.clear();scope.update(session_id='fixture-'+source['alias'],
                task={'actual_speaker_id':source['speaker'],'people':data['people'],'audience_ids':source['audience'],
                      'conversation_at':source['at']})
            conversation.start('authored-fixture',online=True)
            conversation.feed('authored-fixture',{'events':[{'type':'speech_started','utterance':i},
                {'type':'recognition','utterance':i,'final':True,'text':source['text'],'recognition_id':source['alias']}]})
            if not conversation.learning_events or not conversation.learning_events[-1].get('queued'):
                raise ValueError('Actual accepted-turn hook did not queue source')
            capture=deepcopy(conversation.learning_events[-1]);result['captures'].append(capture)
            if capture.get('recognition_id')!=source['alias'] or capture['source_id'] in result['sources'].values():
                raise ValueError('Accepted source was stale or duplicated')
            result['sources'][source['alias']]=capture['source_id'];save()
            await wait_idle(i)
            result.setdefault('ingestion_checkpoints',[]).append({'alias':source['alias'],'completed':i,'state':bank.supervisor.snapshot(),'diagnostics':bank.queue.diagnostics()});save()
            print(json.dumps({'source':source['alias'],'completed':i,'additional_api_usd':result['additional_api_usd']}),flush=True)
        await conversation.close();conversation=None
        result['completed_ingestions']=len(bank.queue.sources());result['queue_before']=bank.queue.evidence_snapshot()
        # Stable recognition ID redelivery does not dispatch another native job.
        first=data['sources'][0];sid=result['sources'][first['alias']]
        original=next(s for s in bank.queue.sources() if s['id']==sid)
        duplicate_scope={'session_id':'fixture-'+first['alias'],'task':{'actual_speaker_id':first['speaker'],'people':data['people'],
            'audience_ids':first['audience'],'conversation_at':first['at']}}
        result['duplicate']=bank.capture(duplicate_scope,None,original['text'],first['alias']);save()
        for case in data['cases']:
            remaining();query_scope={'session_id':'query-'+case['id'],'memory_epoch':bank.generation(),
                'task':{'actual_speaker_id':case['speaker'],'people':data['people'],'audience_ids':case['audience'],
                    'conversation_at':case['at'],'catalogue':[]}}
            if ledger.used_micro_usd()+1000000>cap:raise ValueError('Reply reservation headroom exhausted before retrieval')
            provider=MemoryTextProvider(replies,scope=lambda s=query_scope:{**s,'memory_epoch':bank.generation()},recall=bank.recall,
                reference_factory=reference_factory,evidence_qualifier=with_access_decision);providers.append(provider)
            row={'case_id':case['id'],'completed':False};result['cases'].append(row);save()
            try:
                async with asyncio.timeout(min(60,remaining())):
                    row['text']=''.join([part async for part in provider.stream_reply([{'role':'user','content':case['text']}])])
                observation=deepcopy(provider.observations[-1]);ref=references[-1]
                row.update(completed=True,observation=observation,session=deepcopy(ref.session),wire=deepcopy(ref.wire))
                if not observation['result']['usage_settled']:raise ValueError('Unknown reply usage; reservation preserved')
                save();print(json.dumps({'case':case['id'],'completed':True,'additional_api_usd':result['additional_api_usd']}),flush=True)
            finally:
                if provider.observations:row['observation']=deepcopy(provider.observations[-1])
                await provider.close();save()
        revoked=result['sources'][data['revoke_alias']];bank.queue.revoke(revoked)
        raw=await bank.recall({'actual_speaker_id':'nora','people':data['people'],'audience_ids':['nora'],
            'conversation_at':'2026-11-09T12:00:00Z','question':data['revoke_question']})
        result['revoked_context_excluded']=revoked not in raw['evidence']['source_headers'];result['post_revoke_context']=raw
        result['native_delete']=await asyncio.to_thread(bank._send,{'op':'delete','source_id':revoked})
        result['post_delete_readiness']=await wait_native_readiness(expected_paid=True)
        before=bank.queue.evidence_snapshot();result['before_restart']=before
        directory=bank.directory;await bank.close();save()
        result['between_cycles_readiness']=await wait_native_readiness()
        await bank.prepare();await wait_idle(7)
        result['same_generation_after_restart']=bank.directory==directory
        result['source_state_preserved_after_restart']=bank.queue.evidence_snapshot()==before
        inventory=await asyncio.to_thread(bank._send,{'op':'inventory','people':data['people']})
        result['restart_projection']=projection_report(bank.queue.evidence_snapshot(),inventory)
        result['learning_timing']=bank.queue.diagnostics();save()
    except Exception as error:
        result['errors'].append(type(error).__name__+': '+str(error));save()
    finally:
        for provider in providers:
            try:await provider.close()
            except Exception as e:result['errors'].append('provider_close:'+type(e).__name__)
        if conversation:
            try:await conversation.close()
            except Exception as e:result['errors'].append('conversation_close:'+type(e).__name__)
        try:await bank.close()
        except Exception as e:result['errors'].append('bank_close:'+type(e).__name__)
        for gateway in reversed(gateways):
            try:await asyncio.to_thread(gateway.close)
            except Exception as e:result['errors'].append('gateway_close:'+type(e).__name__)
        fixture_store.close();save()
        try:result['final_readiness']=await wait_native_readiness()
        except Exception as e:result['errors'].append('final_readiness:'+type(e).__name__+': '+str(e))
        save()
        for i,g in enumerate(gateways,1):
            events=g.folder/'gateway/calls.json'
            result.setdefault('gateway_usage',[]).append({'cycle':i,'events':json.loads(events.read_text()) if events.exists() else [],'ceiling':g.project_ceiling_micro_usd})
        save()
    return result


def run():
    require_ssd();os.umask(0o077)
    path=ROOT/'experiments/memory/household-model-protocol-v1.json';plan=read_protocol(path)
    if APPROVED_BUDGET_MICRO_USD!=31000000:raise ValueError('Owner-approved31USDcap required')
    if list((SSD/'runs/scored'/plan['experiment_id']).glob('*/run.json')):raise ValueError('This check already has an attempt; no retry')
    audits=[audit(p.parent) for p in discover_runs()]
    env=json.loads((ROOT/'experiments/memory/learning-environment-v1.json').read_text())
    for f in env['files']:
        if digest(f['path'])!=f['sha256']:raise ValueError('Native environment/model changed')
    data=json.loads((ROOT/plan['inputs'][0]).read_text());validate_inputs(data)
    ledger=Store(ROOT/'.tavi/simulation/simulation.sqlite3',must_exist=True)
    try:
        if ledger.used_micro_usd()!=plan['configuration']['ledger_anchor_micro_usd']:raise ValueError('Ledger changed; refresh prospective envelope')
        readiness=native_readiness();folder,plan=begin(path,run_root=SSD/'runs/scored')
        print(json.dumps({'run':str(folder),'prior_valid':len(audits),'audit':audit(folder),'readiness':readiness}),flush=True)
        result=asyncio.run(collect(folder,plan,data,ledger))
        print(json.dumps({'run':str(folder),'completed_sources':result.get('completed_ingestions',0),'replies':sum(c['completed'] for c in result['cases']),
            'errors':result['errors'],'additional_api_usd':result['additional_api_usd'],'awaiting':'Frozen semantic labels, actual-wire/usage verification and critical review; no automatic live activation'}),flush=True)
    finally:ledger.close()


if __name__=='__main__':run()
