"""Local journal/index reconciliation. Matching bytes do not verify semantic truth."""
import hashlib
import json
import asyncio


def native_inventory(db, *, maximum_sources=10000):
    """Read only the worker's provenance ledger, never generated fact prose."""
    if db.execute('SELECT count(*) FROM episodes').fetchone()[0]>maximum_sources:
        raise ValueError('Native source inventory exceeds its bound')
    result=[]
    for sid,body,complete,deleted in db.execute('SELECT id,body,complete,deleted FROM episodes ORDER BY id'):
        source=json.loads(body)
        if (not isinstance(source,dict) or source.get('id')!=sid
                or complete not in (0,1) or deleted not in (0,1)):
            raise ValueError('Native source inventory is inconsistent')
        result.append({'id':sid,'sha':hashlib.sha256(body.encode()).hexdigest(),
                       'complete':bool(complete),'deleted':bool(deleted)})
    return result


async def verified_inventory(worker, people):
    """Verify actual Hindsight source documents with read-only GETs, no recall.

    Does not validate extracted assertions, vectors or semantic retrieval.
    """
    if worker.engine!='hindsight':raise ValueError('Unqualified native engine')
    inventory=native_inventory(worker.db,maximum_sources=500)
    async with asyncio.timeout(20):
        for row in inventory:
            if not row['complete']:continue
            source=json.loads(worker.db.execute('SELECT body FROM episodes WHERE id=?',(row['id'],)).fetchone()[0])
            bank=worker.namespace(source['audience_ids'])
            try:
                document=await worker.client.documents.get_document(bank_id=bank,document_id=row['id'],_request_timeout=2.0)
            except Exception as error:
                if getattr(error,'status',None)!=404:raise
                row['document_verified']=row['deleted']
            else:
                row['document_verified']=bool(not row['deleted'] and document.id==row['id']
                    and document.bank_id==bank and document.original_text==worker.source_content(source,people))
    return inventory


def projection_report(view, native):
    """Refuse partial success, stale restores and silent index/source mismatches.

    This is admission metadata, not proof that a native database contains every
    asserted fact. No repair, replay, deletion or live activation occurs here.
    """
    sources={r['id']:r for r in view['records']};indexed={}
    for r in native:
        if (not isinstance(r,dict) or not isinstance(r.get('id'),str) or r['id'] in indexed
                or not isinstance(r.get('sha'),str) or len(r['sha'])!=64
                or any(type(r.get(k)) is not bool for k in ('complete','deleted'))):
            raise ValueError('Invalid native source inventory')
        indexed[r['id']]=r
    issues=[];ambiguous=False
    for sid,source in sources.items():
        item=indexed.get(sid);state=source['state']
        if state=='working':issues.append({'source_id':sid,'reason':'unresolved_working_job'});ambiguous=True
        if item and item['sha']!=source['sha']:
            issues.append({'source_id':sid,'reason':'source_bytes_changed'});continue
        if state=='complete' and (not item or not item['complete'] or item['deleted']):
            issues.append({'source_id':sid,'reason':'missing_or_incomplete_projection'})
        elif state=='complete' and item.get('document_verified') is not True:
            issues.append({'source_id':sid,'reason':'native_document_unverified'})
        elif state=='revoked' and item and not item['deleted']:
            issues.append({'source_id':sid,'reason':'revocation_not_projected'})
        elif state=='revoked' and item and item.get('document_verified') is not True:
            issues.append({'source_id':sid,'reason':'native_deletion_unverified'})
        elif state=='pending' and item:
            issues.append({'source_id':sid,'reason':'unacknowledged_native_dispatch'});ambiguous=True
    for sid in indexed.keys()-sources.keys():issues.append({'source_id':sid,'reason':'unbound_native_source'})
    status='needs_reconciliation' if ambiguous else 'rebuild_required' if issues else 'consistent'
    return {'status':status,'issues':issues,'canonical_sources':len(sources),'native_sources':len(indexed),
            'revocation_epoch':view['epoch'],'can_resume':not issues}
