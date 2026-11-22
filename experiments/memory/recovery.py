"""Durable experiment coordinator with conservative scope quarantine/rebuild.

A process can die anywhere after native dispatch. Never trust a half-written
namespace on restart. Rebuild the affected audience in a fresh generation and
publish its pointer in one SQLite transaction. Old generations are quarantined
for fictional failure analysis, not physical-erasure credit. All pending scopes
block reads; unrelated audiences can still operate. One coordinator owns a file.
"""
import json
import sqlite3
from pathlib import Path
from uuid import uuid4


class Journal:
    def __init__(self, directory):
        self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.directory/'journal.sqlite3')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,body TEXT NOT NULL,scope TEXT NOT NULL,deleted INT NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS scopes(scope TEXT PRIMARY KEY,generation TEXT NOT NULL,dirty INT NOT NULL);
        CREATE TABLE IF NOT EXISTS operations(seq INTEGER PRIMARY KEY,kind TEXT NOT NULL,source_id TEXT,scope TEXT NOT NULL,state TEXT NOT NULL);
        ''')

    @staticmethod
    def scope(audience):
        if not audience or len(audience)!=len(set(audience)) or any(p not in ('p1','p2','p3','p4') for p in audience):
            raise ValueError('Explicit valid fictional audience required')
        return '-'.join(sorted(audience))

    def prepare(self, episode):
        scope=self.scope(episode['audience_ids']);encoded=json.dumps(episode,sort_keys=True)
        row=self.db.execute('SELECT body,deleted FROM sources WHERE id=?',(episode['id'],)).fetchone()
        if row:
            if row[0]!=encoded:raise ValueError('Conflicting canonical source ID')
            return {'duplicate':True,'deleted':bool(row[1]),'scope':scope}
        with self.db:
            self.db.execute('INSERT INTO sources VALUES (?,?,?,0)',(episode['id'],encoded,scope))
            self.db.execute('INSERT OR IGNORE INTO scopes VALUES (?,?,0)',(scope,'g'+uuid4().hex))
            previous=self.db.execute('SELECT dirty FROM scopes WHERE scope=?',(scope,)).fetchone()[0]
            self.db.execute('UPDATE scopes SET dirty=1 WHERE scope=?',(scope,))
            seq=self.db.execute("INSERT INTO operations(kind,source_id,scope,state) VALUES ('ingest',?,?,'pending')",(episode['id'],scope)).lastrowid
        return {'duplicate':False,'scope':scope,'seq':seq,'requires_rebuild':bool(previous)}

    def tombstone(self, sid):
        row=self.db.execute('SELECT scope,deleted FROM sources WHERE id=?',(sid,)).fetchone()
        if not row:raise ValueError('Unknown source')
        if row[1]:return {'duplicate':True,'scope':row[0]}
        with self.db:
            self.db.execute('UPDATE sources SET deleted=1 WHERE id=?',(sid,))
            self.db.execute('UPDATE scopes SET dirty=1 WHERE scope=?',(row[0],))
            seq=self.db.execute("INSERT INTO operations(kind,source_id,scope,state) VALUES ('delete',?,?,'pending')",(sid,row[0])).lastrowid
        return {'duplicate':False,'scope':row[0],'seq':seq}

    def generation(self, scope):
        return self.db.execute('SELECT generation,dirty FROM scopes WHERE scope=?',(scope,)).fetchone()

    def sources(self, scope=None):
        query='SELECT body FROM sources WHERE deleted=0';args=()
        if scope is not None:query+=' AND scope=?';args=(scope,)
        return [json.loads(row[0]) for row in self.db.execute(query+' ORDER BY rowid',args)]

    def pending(self):
        return [row[0] for row in self.db.execute('SELECT scope FROM scopes WHERE dirty=1 ORDER BY scope')]

    def publish(self, scope, generation):
        with self.db:
            self.db.execute('UPDATE scopes SET generation=?,dirty=0 WHERE scope=?',(generation,scope))
            self.db.execute("UPDATE operations SET state='complete' WHERE scope=? AND state='pending'",(scope,))

    def readable(self,audience):
        audience=set(self.scope(audience).split('-'));allowed=[]
        for scope,generation,dirty in self.db.execute('SELECT scope,generation,dirty FROM scopes'):
            if not audience<=set(scope.split('-')):continue
            if dirty:raise RuntimeError('Memory scope quarantined; recovery required')
            allowed.append((scope,generation))
        return sorted(allowed)

    def close(self):self.db.close()
