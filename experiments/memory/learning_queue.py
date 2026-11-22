"""Opt-in accepted-turn learning seam; no production microphone wiring.

Canonical literal source, speaker/audience/time and job state remain local.
Semantic extraction belongs to the native engine, not this queue.
"""
from copy import deepcopy
from collections import deque
import hashlib
import json
import sqlite3
from pathlib import Path
from uuid import uuid4
from experiments.memory.guarded_worker import source_rejection
from experiments.memory import learning_timing
from tavi.chunked_conversation import ChunkedConversation
from tavi.conversation_providers import LOCAL_REPLIES

class LearningQueue:
    def __init__(self,path, *, maximum_pending=16):
        if (Path(path).parent/'RESTORE_OFFLINE_ONLY.json').exists():
            raise ValueError('Offline restored queue: review ambiguous jobs and rebuild native projections before activation')
        self.path=path;self.maximum_pending=maximum_pending
        self.db=sqlite3.connect(path,timeout=.05)
        self.db.row_factory=sqlite3.Row
        if self.db.execute('PRAGMA journal_mode=WAL').fetchone()[0].lower()!='wal':raise ValueError('WAL unavailable')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('''CREATE TABLE IF NOT EXISTS learning(
          id TEXT PRIMARY KEY,body TEXT NOT NULL,sha TEXT NOT NULL,
          state TEXT NOT NULL DEFAULT 'pending',job TEXT,revision INTEGER NOT NULL DEFAULT 1)''')
        self.db.execute('CREATE TABLE IF NOT EXISTS learning_meta(id INTEGER PRIMARY KEY CHECK(id=1),revocation_epoch INTEGER NOT NULL)')
        learning_timing.initialize(self.db)
        with self.db:self.db.execute('INSERT OR IGNORE INTO learning_meta VALUES(1,0)')
    def capture(self,scope,token,text,recognition_id):
        task=scope['task']
        # A delivered recognition has a stable ID across controller retries.
        # Repeating a sentence with a NEW recognition is a distinct episode.
        key=(scope['session_id'],recognition_id) if isinstance(recognition_id,str) and recognition_id else (scope['session_id'],token.response_id)
        sid='accepted:'+hashlib.sha256(json.dumps(key).encode()).hexdigest()
        source={'id':sid,'session':scope['session_id'],
                'speaker_id':task['actual_speaker_id'],'audience_ids':deepcopy(task['audience_ids']),
                'at':task['conversation_at'],'text':text}
        reason=source_rejection(source,task['people'])
        if reason:return {'queued':False,'reason':reason}
        if not isinstance(text,str) or not 0<len(text)<=2000:raise ValueError('Source text bound')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old=self.db.execute('SELECT body,state FROM learning WHERE id=?',(source['id'],)).fetchone()
            if old:
                # Original event time survives redelivery; no reattribution.
                source['at']=json.loads(old['body'])['at']
                body=json.dumps(source,sort_keys=True)
                if old['body']!=body:raise ValueError('Accepted source ID changed')
                return {'queued':False,'duplicate':True,'source_id':source['id'],'state':old['state']}
            if self.pending()>=self.maximum_pending:return {'queued':False,'reason':'learning_backlog'}
            body=json.dumps(source,sort_keys=True);sha=hashlib.sha256(body.encode()).hexdigest()
            self.db.execute('INSERT INTO learning(id,body,sha) VALUES(?,?,?)',(source['id'],body,sha))
            learning_timing.record(self.db,source['id'],'captured')
        return {'queued':True,'source_id':source['id'],'recognition_id':recognition_id}
    def claim(self):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            r=self.db.execute("SELECT * FROM learning WHERE state='pending' ORDER BY rowid LIMIT 1").fetchone()
            if not r:return None
            job=uuid4().hex;self.db.execute("UPDATE learning SET state='working',job=? WHERE id=?",(job,r['id']))
            learning_timing.record(self.db,r['id'],'claimed',job)
        return {'source':json.loads(r['body']),'sha':r['sha'],'revision':r['revision'],'job':job}
    def complete(self,job):
        with self.db:
            changed=self.db.execute("UPDATE learning SET state='complete',job=NULL WHERE id=? AND sha=? AND revision=? AND job=? AND state='working'",(job['source']['id'],job['sha'],job['revision'],job['job'])).rowcount==1
            if changed:learning_timing.record(self.db,job['source']['id'],'completed',job['job'])
            return changed
    def note_work(self,job,event):
        if event not in ('dispatched','ambiguous','aborted'):raise ValueError('Unknown learning transition')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row=self.db.execute("SELECT 1 FROM learning WHERE id=? AND sha=? AND revision=? AND job=? AND state='working'",(job['source']['id'],job['sha'],job['revision'],job['job'])).fetchone()
            if not row:return False
            # One transition per owned attempt, including repeated cleanup.
            if not self.db.execute('SELECT 1 FROM learning_timing WHERE source_id=? AND job=? AND event=?',(job['source']['id'],job['job'],event)).fetchone():
                learning_timing.record(self.db,job['source']['id'],event,job['job'])
            return True
    def recover_stopped_job(self,job):
        # Supervisor must have confirmed the owning worker stopped. No bulk
        # reset of jobs that could still be running in another process.
        with self.db:
            changed=self.db.execute("UPDATE learning SET state='pending',job=NULL WHERE id=? AND job=? AND state='working'",(job['source']['id'],job['job'])).rowcount==1
            if changed:learning_timing.record(self.db,job['source']['id'],'recovered',job['job'])
            return changed
    def revoke(self,source_id):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old=self.db.execute('SELECT job FROM learning WHERE id=?',(source_id,)).fetchone()
            changed=self.db.execute("UPDATE learning SET state='revoked',revision=revision+1,job=NULL WHERE id=? AND state!='revoked'",(source_id,)).rowcount==1
            if changed:
                self.db.execute('UPDATE learning_meta SET revocation_epoch=revocation_epoch+1 WHERE id=1')
                learning_timing.record(self.db,source_id,'revoked',old['job'])
            return changed
    def diagnostics(self, *, limit=100):
        if type(limit) is not int or not 1<=limit<=1000:raise ValueError('Bounded diagnostic source count required')
        # A consistent read, including when another connection commits a job.
        self.db.execute('BEGIN')
        try:
            rows=self.db.execute('SELECT id,state,revision FROM learning ORDER BY rowid DESC LIMIT ?',(limit,)).fetchall()
            counts={r[0]:r[1] for r in self.db.execute('SELECT state,count(*) FROM learning GROUP BY state')}
            sources=[learning_timing.source_report(self.db,r) for r in reversed(rows)]
            return {'counts':counts,'sources':sources,'sources_truncated':sum(counts.values())>len(rows),'clock_note':'Cross-process wall-clock estimates include downtime and may include clock adjustments; missing legacy timing is not reconstructed. Native dispatch-to-outcome includes transport/local acknowledgement, not pure model latency.'}
        finally:self.db.rollback()
    def generation(self):return self.db.execute('SELECT revocation_epoch FROM learning_meta WHERE id=1').fetchone()[0]
    def evidence_snapshot(self):
        """One consistent authoritative view; never promote pending/ambiguous jobs."""
        self.db.execute('BEGIN')
        try:
            epoch=self.generation();sources=[];revoked=[];records=[]
            for row in self.db.execute('SELECT id,body,sha,state,job,revision FROM learning ORDER BY rowid'):
                body=json.loads(row['body'])
                if (not isinstance(body,dict) or body.get('id')!=row['id']
                        or hashlib.sha256(row['body'].encode()).hexdigest()!=row['sha']
                        or row['state'] not in ('pending','working','complete','revoked')
                        or type(row['revision']) is not int or row['revision']<1
                        or (row['state']=='working' and not row['job'])
                        or (row['state']!='working' and row['job'] is not None)):
                    raise ValueError('Canonical learning record is inconsistent')
                records.append({k:row[k] for k in ('id','sha','state','revision')})
                if row['state']=='complete':sources.append(body)
                elif row['state']=='revoked':revoked.append(row['id'])
            return {'epoch':epoch,'sources':sources,'revoked_source_ids':revoked,'records':records}
        finally:self.db.rollback()
    def working(self):return self.db.execute("SELECT count(*) FROM learning WHERE state='working'").fetchone()[0]
    def sources(self):
        return [json.loads(r[0]) for r in self.db.execute("SELECT body FROM learning WHERE state='complete' ORDER BY rowid")]
    def pending(self):return self.db.execute("SELECT count(*) FROM learning WHERE state IN ('pending','working')").fetchone()[0]
    def close(self):self.db.close()

class LearningConversation(ChunkedConversation):
    def __init__(self,*args,learning_queue,learning_notify=lambda:None,learning_prepare=lambda:None,**kwargs):
        self.learning_queue=learning_queue;self.learning_notify=learning_notify;self.learning_prepare=learning_prepare;self.learning_events=deque(maxlen=64)
        super().__init__(*args,**kwargs)
    def _schedule_reply(self,token,local_reply):
        learnable=self.online and (local_reply is None or local_reply==LOCAL_REPLIES['listen'])
        if learnable and token==self.controller.token:self.learning_prepare()
        super()._schedule_reply(token,local_reply)
        # Only final, engaged human turns accepted by the existing controller.
        # Listen-only turns may contain significant human events. Preserve them
        # with the actual timestamp; only the acknowledgement bypasses reasoning.
        # Offline/control/greeting/generated assistant speech remain excluded.
        if not learnable or token!=self.controller.token or not self.response_context:return
        scope=deepcopy(self.response_context[1])
        if self.history and self.history[-1]['role']=='user':
            try:event=self.learning_queue.capture(scope,token,self.history[-1]['content'],self.accepted_recognition_id)
            except (sqlite3.Error,OSError,ValueError):event={'queued':False,'reason':'local_learning_storage_error'}
            self.learning_events.append(event)
            if event.get('queued'):self.learning_notify()
