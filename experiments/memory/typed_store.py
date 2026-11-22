"""Isolated durable canonical ledger for the typed-memory prototype.

No model, network, microphone or native-engine calls. This is not wired to the
voice app. Publication requires a still-current job token and exact source
binding; deletion/correction/cancellation invalidate late worker completions.
"""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import uuid

from experiments.memory.typed_lookup import MemorySnapshot, source_digest

APPLICATION_ID = 0x50504D31


class TypedMemoryStore:
    def __init__(self, path):
        self.path = Path(path)
        self.db = sqlite3.connect(self.path, timeout=5)
        self.db.row_factory = sqlite3.Row
        tables = {r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        app = self.db.execute('PRAGMA application_id').fetchone()[0]
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        if tables and (app != APPLICATION_ID or version != 1):
            self.db.close()
            raise ValueError('Refusing an unrelated or unsupported database')
        mode = self.db.execute('PRAGMA journal_mode=WAL').fetchone()[0]
        self.db.execute('PRAGMA synchronous=FULL')
        if mode != 'wal' or self.db.execute('PRAGMA synchronous').fetchone()[0] != 2:
            self.db.close()
            raise ValueError('Required durable SQLite settings unavailable')
        self.db.executescript(f'''
            CREATE TABLE IF NOT EXISTS sources (
                id TEXT PRIMARY KEY, body TEXT NOT NULL, source_hash TEXT NOT NULL,
                generation INTEGER NOT NULL, deleted INTEGER NOT NULL DEFAULT 0,
                state TEXT NOT NULL, job_token TEXT, result TEXT);
            CREATE TABLE IF NOT EXISTS versions (
                id TEXT NOT NULL, generation INTEGER NOT NULL, body TEXT NOT NULL,
                source_hash TEXT NOT NULL, deleted INTEGER NOT NULL,
                PRIMARY KEY(id,generation));
            PRAGMA application_id={APPLICATION_ID};
            PRAGMA user_version=1;
        ''')

    def put(self, source, *, correct=False):
        # Validation of semantic content belongs to the admission worker.
        required = {'id', 'speaker_id', 'text', 'at', 'session', 'audience_ids'}
        if not required <= set(source) or not source['audience_ids']:
            raise ValueError('Incomplete canonical source')
        encoded = json.dumps(source, sort_keys=True)
        sha = source_digest(source)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old = self.db.execute('SELECT * FROM sources WHERE id=?', (source['id'],)).fetchone()
            if old and old['source_hash'] == sha:
                return {'state': old['state'], 'changed': False, 'generation': old['generation']}
            if old and (not correct or old['deleted']):
                raise ValueError('Changed source requires explicit correction; tombstones cannot be resurrected')
            generation = old['generation'] + 1 if old else 1
            self.db.execute('INSERT INTO versions VALUES (?,?,?,?,0)',
                            (source['id'], generation, encoded, sha))
            self.db.execute('''INSERT INTO sources VALUES (?,?,?,?,0,'pending',NULL,NULL)
                ON CONFLICT(id) DO UPDATE SET body=excluded.body,source_hash=excluded.source_hash,
                generation=excluded.generation,state='pending',job_token=NULL,result=NULL''',
                (source['id'], encoded, sha, generation))
        return {'state': 'pending', 'changed': True, 'generation': generation}

    def claim_next(self):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row = self.db.execute("SELECT * FROM sources WHERE deleted=0 AND state='pending' ORDER BY rowid LIMIT 1").fetchone()
            if row is None:
                return None
            token = uuid.uuid4().hex
            self.db.execute("UPDATE sources SET state='working',job_token=? WHERE id=?", (token, row['id']))
            return {'token': token, 'generation': row['generation'], 'source': json.loads(row['body']),
                    'source_sha256': row['source_hash']}

    def complete(self, job, proposals, validation, people):
        result = {'source_id': job['source']['id'], 'source_sha256': job['source_sha256'],
                  'proposals': deepcopy(proposals), 'validation': deepcopy(validation)}
        probe = MemorySnapshot(people, [job['source']], [result])
        if probe.pending:
            raise ValueError('Unbound admission cannot be published')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            changed = self.db.execute('''UPDATE sources SET state='complete',result=?,job_token=NULL
                WHERE id=? AND generation=? AND source_hash=? AND deleted=0
                AND state='working' AND job_token=?''',
                (json.dumps(result), job['source']['id'], job['generation'], job['source_sha256'], job['token'])).rowcount
        return changed == 1

    def invalidate_job(self, token):
        """Supervisor cancels one job or reconciles a known-stopped worker.

        Does not retry inference or assume all other workers are dead.
        A later completion with the invalidated token cannot publish.
        """
        with self.db:
            return self.db.execute("UPDATE sources SET state='pending',job_token=NULL WHERE state='working' AND job_token=? AND deleted=0", (token,)).rowcount == 1

    def delete(self, source_id):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old = self.db.execute('SELECT * FROM sources WHERE id=?', (source_id,)).fetchone()
            if old is None or old['deleted']:
                return False
            generation = old['generation'] + 1
            self.db.execute('INSERT INTO versions VALUES (?,?,?,?,1)',
                            (source_id, generation, old['body'], old['source_hash']))
            self.db.execute("UPDATE sources SET generation=?,deleted=1,state='deleted',job_token=NULL,result=NULL WHERE id=?", (generation, source_id))
        return True

    def snapshot(self, people):
        with self.db:
            self.db.execute('BEGIN')
            rows = self.db.execute('SELECT * FROM sources ORDER BY rowid').fetchall()
        sources, results, deleted = [], [], []
        for row in rows:
            sources.append(json.loads(row['body']))
            if row['deleted']:
                deleted.append(row['id'])
            results.append(json.loads(row['result']) if row['result'] else {
                'source_id': row['id'], 'source_sha256': row['source_hash'],
                'proposals': [], 'validation': None})
        return MemorySnapshot(people, sources, results, deleted_source_ids=deleted)

    def close(self):
        self.db.close()
