"""Private offline queue archives; never restore native projections or spending.

Internal primitive, not an automatic live-restore command. A new restored copy
is quarantined before any DB bytes appear and cannot be opened by LearningQueue.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
from uuid import uuid4

FORMAT='paprika-learning-queue-offline-v1'
MARKER='RESTORE_OFFLINE_ONLY.json'
COLUMNS={
    'learning':{'id','body','sha','state','job','revision'},
    'learning_meta':{'id','revocation_epoch'},
    'learning_timing':{'sequence','source_id','event','job','wall_ns','monotonic_ns','clock_domain'}}


def _guard(path):
    path=Path(path)
    if path.is_symlink():raise ValueError('Queue archive paths cannot be symlinks')
    if len(path.parts)>2 and path.parts[1]=='Volumes' and not Path(*path.parts[:3]).is_mount():
        raise ValueError('External drive is unavailable; do not create a lookalike folder')
    return path


def _read_db(path):
    path=_guard(Path(path).absolute())
    if not path.is_file() or path.stat().st_size>256_000_000:raise ValueError('Bounded existing queue database required')
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=.1)
    db.execute('PRAGMA trusted_schema=OFF')
    return db


def _summary(db):
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    if tables!=set(COLUMNS):raise ValueError('Only the learning queue schema can be archived')
    for table,columns in COLUMNS.items():
        if {r[1] for r in db.execute(f'PRAGMA table_info({table})')}!=columns:raise ValueError('Unqualified queue schema')
    if db.execute('PRAGMA quick_check').fetchall()!=[('ok',)]:raise ValueError('Queue integrity check failed')
    meta=db.execute('SELECT id,revocation_epoch FROM learning_meta').fetchall()
    if len(meta)!=1 or meta[0][0]!=1 or type(meta[0][1]) is not int or meta[0][1]<0:raise ValueError('Invalid revocation epoch')
    for sid,body,sha,state,job,revision in db.execute('SELECT id,body,sha,state,job,revision FROM learning'):
        if (hashlib.sha256(body.encode()).hexdigest()!=sha or json.loads(body).get('id')!=sid
                or state not in ('pending','working','complete','revoked') or type(revision) is not int or revision<1
                or (state=='working' and (not isinstance(job,str) or not job)) or (state!='working' and job is not None)):
            raise ValueError('Queue source or job state is inconsistent')
    return {'counts':dict(db.execute('SELECT state,count(*) FROM learning GROUP BY state')),
            'revocation_epoch':meta[0][1],'timing_events':db.execute('SELECT count(*) FROM learning_timing').fetchone()[0]}


def _digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1<<20),b''):h.update(block)
    return h.hexdigest()


def _json(path,value):
    path=_guard(path);raw=(json.dumps(value,indent=2)+'\n').encode()
    with os.fdopen(os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'wb') as out:
        out.write(raw);out.flush();os.fsync(out.fileno())


def _new_directory(parent,prefix):
    parent=_guard(Path(parent).absolute())
    if not parent.is_dir():raise ValueError('Archive parent must already exist')
    target=parent/(prefix+uuid4().hex);target.mkdir(mode=0o700,exist_ok=False)
    return target


def snapshot_queue(source,parent):
    source_db=_read_db(source)
    try:
        _summary(source_db) # Reject unrelated DBs before creating a destination.
        target=_new_directory(parent,'queue-snapshot-');dest=target/'queue.sqlite3'
        fd=os.open(dest,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        out=sqlite3.connect(dest);deadline=time.monotonic()+10
        def progress(*_):
            if time.monotonic()>deadline:raise TimeoutError('Queue snapshot deadline exceeded')
        try:
            source_db.backup(out,pages=64,progress=progress,sleep=.01)
            out.execute('PRAGMA journal_mode=DELETE')
            summary=_summary(out)
        finally:out.close()
        _guard(target)
        with dest.open('rb') as stream:os.fsync(stream.fileno())
        # This is the completion marker, written only after a consistent DB.
        _json(target/'manifest.json',{'format':FORMAT,'complete':True,'database_sha256':_digest(dest),
            'summary':summary,'native_projection_included':False,'spend_ledger_included':False,
            'can_activate_live':False})
        return target
    finally:source_db.close()


def verify_snapshot(folder):
    folder=_guard(Path(folder).absolute());manifest=folder/'manifest.json'
    if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size>16384:raise ValueError('Completed queue manifest required')
    value=json.loads(manifest.read_text())
    if (value.get('format')!=FORMAT or value.get('complete') is not True
            or value.get('native_projection_included') is not False or value.get('spend_ledger_included') is not False
            or value.get('can_activate_live') is not False):raise ValueError('Unqualified queue archive')
    db_path=_guard(folder/'queue.sqlite3')
    if _digest(db_path)!=value['database_sha256']:raise ValueError('Queue archive checksum changed')
    db=_read_db(db_path)
    try:
        if _summary(db)!=value['summary']:raise ValueError('Queue archive summary changed')
    finally:db.close()
    return value


def restore_offline(folder,parent):
    value=verify_snapshot(folder)
    target=_new_directory(parent,'queue-offline-restore-')
    _json(target/MARKER,{'state':'offline_restore_requires_review','native_projection_ready':False,
        'source_database_sha256':value['database_sha256'],'automatic_replay_allowed':False,
        'reason':'Review pending/ambiguous work and rebuild/qualify native projections before any activation.'})
    dest=target/'queue.sqlite3'
    # Pre-create600 and copy bytes without importing archive filesystem modes.
    with os.fdopen(os.open(dest,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'wb') as out:
        with (Path(folder)/'queue.sqlite3').open('rb') as source:shutil.copyfileobj(source,out)
        out.flush();os.fsync(out.fileno())
    _guard(target)
    if _digest(dest)!=value['database_sha256']:raise ValueError('Offline restore copy changed; keep it quarantined')
    _json(target/'restored-manifest.json',value)
    return target
