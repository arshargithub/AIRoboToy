"""Zero-inference PostgreSQL recovery fixtures; never restore an active database.

Uses the installed native schema, new uniquely named databases and authored
records only. No Hindsight server/worker, broker, retain or recall is started.
"""
import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
from types import SimpleNamespace
import unittest
from uuid import uuid4

from experiments.memory.runtime import ROOT, SSD, require_ssd
from experiments.memory.learning_queue import LearningQueue
from experiments.memory.queue_snapshot import snapshot_queue, restore_offline
from experiments.memory.worker import Worker
from tavi.household_memory import HouseholdMemory
from tavi.memory_projection import projection_report, verified_inventory
from tavi.experiment_workflow import begin, finish, audit, discover_runs, digest

BIN=SSD/'databases/pg0/installation/18.1.0/bin'
PREP=ROOT/'.tavi/private-memory-recovery'


def connection_info():
    import psycopg2.extensions
    return psycopg2.extensions.parse_dsn(json.loads((SSD/'private-config/postgres.json').read_text())['uri'])


def connect(name=None):
    import psycopg2
    info=connection_info()
    if name is not None:info['dbname']=name
    return psycopg2.connect(**info)


def command(tool,db,*args):
    info=connection_info();env={**os.environ,'PGDATABASE':db,'PGCONNECT_TIMEOUT':'5'}
    for key,name in [('host','PGHOST'),('port','PGPORT'),('user','PGUSER'),('password','PGPASSWORD')]:
        if key in info:env[name]=info[key]
    result=subprocess.run([str(BIN/tool),*map(str,args)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60)
    if result.returncode:raise RuntimeError(tool+' failed; fixture retained, no automatic retry')


def prepare_schema():
    require_ssd();PREP.mkdir(mode=0o700,exist_ok=False)
    os.umask(0o077)
    command('pg_dump',connection_info()['dbname'],'--schema-only','--no-owner','--no-acl','--file',PREP/'schema.sql')
    c=connect()
    try:
        with c.cursor() as q:q.execute('show server_version');version=q.fetchone()[0]
    finally:c.close()
    (PREP/'environment.json').write_text(json.dumps({'server_version':version,'schema_only':True,
        'schema_sha256':digest(PREP/'schema.sql'),'tools_sha256':{n:digest(BIN/n) for n in ['pg_dump','pg_restore','psql']},
        'source_records_exported':False},indent=2)+'\n')
    print(json.dumps({'preparation':str(PREP),'server_version':version,'source_records_exported':False}))


def create_database(name):
    from psycopg2 import sql
    if not name.startswith('paprika_recovery_') or not name.replace('_','').isalnum():raise ValueError('Fixture database name required')
    c=connect();c.autocommit=True
    try:
        with c.cursor() as q:q.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    finally:c.close()


def verify_archive(folder):
    folder=Path(folder);manifest=folder/'native-manifest.json'
    if manifest.is_symlink() or manifest.stat().st_size>16384:raise ValueError('Invalid native manifest')
    value=json.loads(manifest.read_text())
    if (value.get('format')!='paprika-native-fixture-offline-v1' or value.get('complete') is not True
            or value.get('fixture_only') is not True or value.get('can_activate_live') is not False
            or value.get('spend_ledger_included') is not False):raise ValueError('Unqualified native archive')
    for name,sha in value['files'].items():
        if name not in ('native.dump','source-ledger.sqlite3'):raise ValueError('Unexpected native archive file')
        f=folder/name
        if f.is_symlink() or not f.is_file() or f.stat().st_size>256000000 or digest(f)!=sha:
            raise ValueError('Native archive checksum failed')
    if set(value['files'])!={'native.dump','source-ledger.sqlite3'}:raise ValueError('Incomplete native archive')
    with (folder/'native.dump').open('rb') as f:
        if f.read(5)!=b'PGDMP':raise ValueError('Not a PostgreSQL custom archive')
    return value


def database_rows(name):
    c=connect(name)
    try:
        with c.cursor() as q:
            result={}
            for table,order in [('banks','bank_id'),('documents','bank_id,id'),('memory_units','id')]:
                q.execute('SELECT row_to_json(t)::text FROM (SELECT * FROM '+table+' ORDER BY '+order+') t')
                result[table]=[json.loads(r[0]) for r in q.fetchall()]
            return result
    finally:c.close()


def schema_signature(name):
    c=connect(name)
    try:
        with c.cursor() as q:
            q.execute("SELECT table_name,column_name,udt_name,is_nullable,column_default FROM information_schema.columns WHERE table_schema='public' ORDER BY table_name,ordinal_position")
            columns=q.fetchall()
            q.execute("SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY tablename,indexname")
            indexes=q.fetchall()
            q.execute("SELECT c.relname,x.conname,pg_get_constraintdef(x.oid) FROM pg_constraint x JOIN pg_class c ON c.oid=x.conrelid JOIN pg_namespace n ON c.relnamespace=n.oid WHERE n.nspname='public' ORDER BY 1,2")
            return {'columns':columns,'indexes':indexes,'constraints':q.fetchall()}
    finally:c.close()


class Documents:
    def __init__(self,name):self.name=name
    async def get_document(self,*,bank_id,document_id,**kw):
        c=connect(self.name)
        try:
            with c.cursor() as q:
                q.execute('SELECT id,bank_id,original_text FROM documents WHERE id=%s AND bank_id=%s',(document_id,bank_id));row=q.fetchone()
        finally:c.close()
        if not row:
            e=ValueError('Fixture source document absent');e.status=404;raise e
        return SimpleNamespace(id=row[0],bank_id=row[1],original_text=row[2])


def worker(db,name):
    return SimpleNamespace(db=db,engine='hindsight',namespace=lambda a:'recoveryfixture-'+'-'.join(sorted(a)),
        source_content=Worker.source_content,client=SimpleNamespace(documents=Documents(name)))


async def fixtures(folder):
    cfg=json.loads((ROOT/'experiments/memory/native-recovery-input-v1.json').read_text());people=cfg['people']
    q=LearningQueue(folder/'canonical.sqlite3');native=sqlite3.connect(folder/'source-ledger.sqlite3');native.execute('CREATE TABLE episodes(id TEXT PRIMARY KEY,body TEXT,complete INTEGER,deleted INTEGER)')
    token=uuid4().hex[:16];source_db='paprika_recovery_'+token+'_source';restored_db='paprika_recovery_'+token+'_offline'
    result={'source_database':source_db,'offline_restore_database':restored_db,'native_inference_started':False,'household_activation':False}
    try:
        ids={};ambiguous=None
        for row in cfg['sources']:
            scope={'session_id':row['session'],'task':{'actual_speaker_id':row['speaker'],'people':people,'audience_ids':row['audience'],'conversation_at':row['at']}}
            sid=q.capture(scope,None,row['text'],row['key'])['source_id'];ids[row['key']]=sid
            if row['state'] in ('complete','working'):
                job=q.claim()
                if row['state']=='complete':q.complete(job)
                else:ambiguous=job;q.note_work(job,'dispatched');q.note_work(job,'ambiguous')
                body=q.db.execute('SELECT body FROM learning WHERE id=?',(sid,)).fetchone()[0]
                native.execute('INSERT INTO episodes VALUES(?,?,1,0)',(sid,body))
        native.commit();create_database(source_db)
        command('psql',source_db,'--set','ON_ERROR_STOP=1','--file',PREP/'schema.sql')
        c=connect(source_db)
        try:
            with c, c.cursor() as cur:
                for sid,body in native.execute('SELECT id,body FROM episodes'):
                    source=json.loads(body);bank=worker(native,source_db).namespace(source['audience_ids']);content=Worker.source_content(source,people)
                    cur.execute('INSERT INTO banks(bank_id,name) VALUES(%s,%s) ON CONFLICT DO NOTHING',(bank,'Authored offline recovery fixture'))
                    cur.execute('INSERT INTO documents(id,bank_id,original_text,content_hash) VALUES(%s,%s,%s,%s)',(sid,bank,content,hashlib.sha256(content.encode()).hexdigest()))
                    vector='['+','.join(['1']+['0']*383)+']'
                    cur.execute('INSERT INTO memory_units(bank_id,document_id,text,embedding) VALUES(%s,%s,%s,%s::vector)',(bank,sid,'Synthetic derivative text is not canonical evidence.',vector))
        finally:c.close()
        before=database_rows(source_db);archive=folder/'native-archive';archive.mkdir(mode=0o700)
        command('pg_dump',source_db,'--format=custom','--no-owner','--no-acl','--file',archive/'native.dump')
        dest=sqlite3.connect(archive/'source-ledger.sqlite3');native.backup(dest);dest.close()
        manifest={'format':'paprika-native-fixture-offline-v1','complete':True,'fixture_only':True,'can_activate_live':False,
            'spend_ledger_included':False,'files':{n:digest(archive/n) for n in ['native.dump','source-ledger.sqlite3']}}
        (archive/'native-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');verify_archive(archive)
        canonical_archive=snapshot_queue(q.path,folder);offline=restore_offline(canonical_archive,folder)
        result['offline_canonical_open_blocked']=False
        try:unsafe=LearningQueue(offline/'queue.sqlite3');unsafe.close()
        except ValueError:result['offline_canonical_open_blocked']=True
        # Revocation AFTER snapshot: the old archive must not override it.
        q.revoke(ids['revoked'])
        (folder/'native-restore-OFFLINE.json').write_text(json.dumps({'database':restored_db,'fixture_only':True,'can_activate_live':False})+'\n')
        create_database(restored_db);command('pg_restore',restored_db,'--no-owner','--no-acl','--single-transaction','--exit-on-error','--dbname',restored_db,archive/'native.dump')
        result['native_rows_equal']=before==database_rows(restored_db)
        result['native_schema_equal']=schema_signature(source_db)==schema_signature(restored_db)
        result['checked_native_data_tables']=len(before);result['native_document_count']=len(before['documents']);result['vectors_restored']=all(r['embedding'] for r in database_rows(restored_db)['memory_units'])
        shutil.copyfile(archive/'source-ledger.sqlite3',folder/'restored-source-ledger.sqlite3')
        restored=sqlite3.connect(folder/'restored-source-ledger.sqlite3');restored.row_factory=sqlite3.Row
        try:
            inventory=await verified_inventory(worker(restored,restored_db),people)
            report=projection_report(q.evidence_snapshot(),inventory);result['stale_archive_report']=report
            result['old_restore_rejected']=not report['can_resume'] and any(i['reason']=='revocation_not_projected' for i in report['issues'])
            result['ambiguous_job_preserved']=report['status']=='needs_reconciliation' and q.working()==1
            # A controlled offline rebuild/resolution, not an automatic live repair.
            c=connect(restored_db)
            try:
                with c,c.cursor() as cur:cur.execute('DELETE FROM documents WHERE id=%s',(ids['revoked'],))
            finally:c.close()
            restored.execute('UPDATE episodes SET deleted=1 WHERE id=?',(ids['revoked'],));restored.commit()
            q.complete(ambiguous)
            inventory=await verified_inventory(worker(restored,restored_db),people)
            result['reconciled_fixture_report']=projection_report(q.evidence_snapshot(),inventory)
            result['reconciled_fixture_consistent']=result['reconciled_fixture_report']['can_resume']
            bank=HouseholdMemory(people);bank.queue=q;bank.ready=True
            class Encoding:
                def encode(self,text):return text.encode()
            bank.encoding=Encoding()
            c=connect(restored_db)
            try:
                with c.cursor() as cur:cur.execute('SELECT id::text,text,document_id FROM memory_units');hints=[{'id':r[0],'text':r[1],'document_id':r[2]} for r in cur.fetchall()]
            finally:c.close()
            bank._send=lambda body:{'native_context':[{'results':hints}]}
            task={'actual_speaker_id':'a','people':people,'audience_ids':['a','b'],'conversation_at':'2026-12-01T12:00:00Z','question':'What breakfast would Mira like now?'}
            raw=await bank.recall(task);context=json.dumps(raw['evidence']);texts=[f['text'] for f in raw['evidence']['facts']]
            result['actual_adapter_source_projection']=cfg['sources'][0]['text'] in texts and cfg['sources'][1]['text'] in texts
            result['private_revoked_derivative_excluded']=all(cfg['sources'][i]['text'] not in context for i in [2,3]) and 'Synthetic derivative text' not in context
            result['correction_preserved_verbatim']=cfg['sources'][1]['text'] in texts
            bank.queue=None;await bank.close()
        finally:restored.close()
        faults=[]
        for kind in ['bytes','truncated','incomplete','live','foreign-file']:
            bad=folder/('corrupt-'+kind);shutil.copytree(archive,bad)
            m=json.loads((bad/'native-manifest.json').read_text())
            if kind=='bytes':(bad/'native.dump').write_bytes(b'changed')
            elif kind=='truncated':(bad/'native.dump').write_bytes(b'PGDMP')
            elif kind=='incomplete':m['complete']=False
            elif kind=='live':m['can_activate_live']=True
            else:m['files']['spending.sqlite3']='0'*64
            (bad/'native-manifest.json').write_text(json.dumps(m))
            try:verify_archive(bad)
            except ValueError:faults.append(kind)
        result['archive_faults_rejected']=len(faults)
        result['source_fixture_unchanged']=database_rows(source_db)==before
        verify_archive(archive)
        result['archives']=dict(native=str(archive),canonical=str(canonical_archive),offline_canonical=str(offline))
        return result
    finally:q.close();native.close()


def run():
    os.umask(0o077);require_ssd();checks=[audit(p.parent) for p in discover_runs()]
    protocol=ROOT/'experiments/memory/native-recovery-protocol-v1.json'
    if list((SSD/'runs/scored/HOUSEHOLD-RECOVERY-01').glob('*/run.json')):raise ValueError('No automatic rerun')
    folder,plan=begin(protocol,run_root=SSD/'runs/scored');print(json.dumps({'run':str(folder),'prior_valid':len(checks),'audit':audit(folder)}),flush=True)
    errors=[];data={};metrics={};ledger=sqlite3.connect((ROOT/'.tavi/simulation/simulation.sqlite3').as_uri()+'?mode=ro',uri=True)
    used=lambda:ledger.execute('SELECT SUM(COALESCE(actual,reserved)) FROM spending').fetchone()[0]
    initial=used()
    try:data=asyncio.run(fixtures(folder))
    except Exception as error:errors.append(type(error).__name__+': '+str(error))
    stream=io.StringIO();tests=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(plan['configuration']['controlled_tests']))
    (folder/'controlled-tests.txt').write_text(stream.getvalue())
    for k in plan['configuration']['boolean_metrics']:metrics[k]=data.get(k)
    metrics.update(archive_faults_rejected=data.get('archive_faults_rejected'),controlled_checks_passed=tests.testsRun-len(tests.errors)-len(tests.failures),test_failures=len(tests.errors)+len(tests.failures),collection_errors=len(errors),additional_api_usd=(used()-initial)/1e6)
    ledger.close();(folder/'observations.json').write_text(json.dumps({'metrics':metrics,'data':data,'errors':errors},indent=2)+'\n')
    artifacts=[p for p in folder.rglob('*') if p.is_file() and p.name not in ('run.json','protocol.json') and not set(p.relative_to(folder).parts)&{'source','context'}]
    record=finish(folder,metrics,artifacts=artifacts,completed=not errors,error=';'.join(errors) or None)
    report={'run':str(folder),'metrics':metrics,'decision':record['decision'],'audit':audit(folder),'data':data,'errors':errors,'limits':['Native PostgreSQL schema/document/vector logical backup restored in two new isolated fixture databases; no active native records copied or replaced.','Source-document validation uses actual PostgreSQL rows through a controlled read-only document facade, not a live Hindsight recall/retain or inference.','Canonical source/native document reconciliation is not proof of generated assertion truth, vector search quality, naturalness or E5.','Fixture ambiguous success is explicitly resolved after controlled offline repair, not automatically acknowledged in production. Old archive remains quarantined.','No real child speech, profiles, calibration, household bank, microphone, provider destination or paid ledger change. No physical cable removal or power-loss claim.']}
    (ROOT/'docs/evaluations/paprika_household_recovery_01.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'run':str(folder),'decision':record['decision']['outcome'],'metrics':metrics,'errors':errors}),flush=True)


if __name__=='__main__':run()
