"""Persistent local household adapter; constructed lazily after trusted gates.

Hindsight is a candidate backend, not a new E5 winner. It nominates original
canonical sources; generated assertion prose is not promoted to identity truth.
"""
import asyncio
from copy import deepcopy
import json
import sqlite3
import threading
from pathlib import Path
from uuid import uuid4
from experiments.memory.guarded_worker import source_rejection
from experiments.memory.runtime import SSD,require_ssd
from experiments.memory.worker_transport import MemoryWorkerUnavailable,MemoryWorkerTimeout
from tavi.memory_projection import projection_report
from tavi.memory_generation import native_directory


class HouseholdMemory:
    # This new adapter boundary needs its own integration and human screen.
    # Earlier isolated Hindsight screens do not authorize household operation.
    qualified=False
    def __init__(self,people,*,storage_root=None,gateway_factory=None,source_realm='household'):
        if source_realm not in ('household','fixture'):raise ValueError('Unknown source realm')
        self.people=people;self.queue=None;self.worker=None;self.supervisor=None;self.gateway=None
        self.directory=None;self.encoding=None;self.lock=threading.Lock();self.ready=False
        self.incarnation=uuid4().hex;self.recovery_status='not_checked'
        self.storage_root=Path(storage_root) if storage_root is not None else None
        self.gateway_factory=gateway_factory
        self.source_realm=source_realm
        self.storage_identity=None

    async def prepare(self):
        if self.ready:return
        if any(x is not None for x in (self.queue,self.worker,self.supervisor,self.gateway)):
            await self.close()
        require_ssd()
        self.incarnation=uuid4().hex;self.recovery_status='checking'
        from experiments.memory.learning_queue import LearningQueue
        from experiments.memory.learning_supervisor import LearningSupervisor,NativeLearningClient
        from experiments.memory.learning_gateway import LearningGateway
        from experiments.memory.pilot import Process
        root=self.storage_root if self.storage_root is not None else SSD/'household/paprika-v1'
        if not root.resolve().is_relative_to(SSD.resolve()):raise ValueError('Household fixture root must stay on the memory drive')
        root.mkdir(parents=True,exist_ok=True,mode=0o700)
        control=root/'sessions'/uuid4().hex;control.mkdir(parents=True,mode=0o700);logs=control/'logs';logs.mkdir(mode=0o700)
        try:
            self.directory=native_directory(root,source_realm=self.source_realm)
            self.queue=LearningQueue(root/'learning.sqlite3',maximum_pending=16)
            stat=Path(self.queue.path).stat();self.storage_identity=(stat.st_dev,stat.st_ino)
            import os,tiktoken
            os.environ['TIKTOKEN_CACHE_DIR']=str(SSD/'models/tiktoken');self.encoding=tiktoken.get_encoding('o200k_base')
            self.worker=Process('hindsight',self.directory,logs,'learning_worker.py',source_realm=self.source_realm)
            await asyncio.to_thread(self._send,{'op':'initialize'})
            inventory=await asyncio.to_thread(self._send,{'op':'inventory','people':self.people})
            report=projection_report(self.queue.evidence_snapshot(),inventory)
            self.recovery_status=report['status']
            if not report['can_resume']:
                raise ValueError('Memory sources and native index need offline reconciliation')
            # Do not enable a paid ingestion gateway for an unresolved store.
            self.gateway=(self.gateway_factory or LearningGateway)(control);await asyncio.to_thread(self.gateway.start)
            self.supervisor=LearningSupervisor(self.queue.path,lambda:NativeLearningClient(self.directory,logs,self.people,source_realm=self.source_realm),maximum_jobs=16)
            self.supervisor.start();self.ready=True
        except BaseException:
            if self.recovery_status=='checking':self.recovery_status='unavailable'
            await self.close();raise

    def _send(self,body):
        with self.lock:
            if not self.worker:raise MemoryWorkerUnavailable('Household memory is unavailable')
            result=self.worker.send(body,timeout=45)
        if not result['ok']:raise MemoryWorkerUnavailable('Household memory is unavailable')
        return result['result']

    def _unavailable(self,reason):
        if self.ready or self.recovery_status!=reason:self.incarnation=uuid4().hex
        self.ready=False;self.recovery_status=reason

    def _check_storage(self):
        if self.storage_identity is None:return # Unprepared controlled adapters have no mounted store.
        try:
            require_ssd()
            stat=Path(self.queue.path).stat()
            if (stat.st_dev,stat.st_ino)!=self.storage_identity:
                raise OSError('Canonical database was replaced')
        except (OSError,RuntimeError) as error:
            self._unavailable('storage_unavailable')
            raise MemoryWorkerUnavailable('The memory drive or canonical store is unavailable') from error

    async def recall(self,task):
        if not self.ready or not self.queue:raise MemoryWorkerUnavailable('Household memory is not ready')
        self._check_storage()
        speaker=task.get('actual_speaker_id');audience=task.get('audience_ids')
        if (not isinstance(speaker,str) or speaker not in self.people or not isinstance(audience,list) or not audience
                or any(not isinstance(p,str) or p not in self.people for p in audience) or speaker not in audience
                or len(set(audience))!=len(audience)):
            raise ValueError('Unknown memory identity or audience')
        if self.supervisor and self.supervisor.snapshot()['status'] in ('needs_reconciliation','owner_busy','job_bound'):
            self._unavailable('needs_reconciliation')
            raise MemoryWorkerUnavailable('Memory learning needs reconciliation')
        from experiments.memory.source_context import pack_sources
        queue=self.queue;issued=self.generation()
        question={'id':uuid4().hex,'asker':task['actual_speaker_id'],'audience_ids':task['audience_ids'],'text':task['question'],'at':task['conversation_at']}
        try:native=await asyncio.to_thread(self._send,{'op':'query','question':question,'people':self.people})
        except (MemoryWorkerUnavailable,MemoryWorkerTimeout):
            self._unavailable('worker_unavailable');raise
        self._check_storage()
        if not self.ready or self.queue is not queue or self.generation()!=issued:
            raise ValueError('Memory store or source permissions changed during retrieval')
        try:view=queue.evidence_snapshot()
        except (sqlite3.Error,OSError,ValueError) as error:
            self._unavailable('storage_unavailable')
            raise MemoryWorkerUnavailable('Canonical memory storage is unavailable') from error
        sources=view['sources']
        if view['epoch']!=issued[1] or any(source_rejection(s,self.people) for s in sources):
            raise ValueError('Memory source view is unqualified')
        packed=pack_sources('hindsight',native['native_context'],sources,task['audience_ids'],self.encoding,
                            as_of=task['conversation_at'],deleted_source_ids=view['revoked_source_ids'],maximum_tokens=1500)
        return {'evidence':json.loads(packed['context']),'sources':sources}

    def capture(self,*args):
        if not self.ready:return {'queued':False,'reason':'memory_not_ready'}
        try:self._check_storage()
        except MemoryWorkerUnavailable:return {'queued':False,'reason':'memory_not_ready'}
        return self.queue.capture(*args)

    def notify(self):
        if self.supervisor:self.supervisor.notify()

    def generation(self):
        try:
            self._check_storage()
            return (self.incarnation,self.queue.generation() if self.queue else 0)
        except (sqlite3.Error,OSError) as error:
            self._unavailable('storage_unavailable')
            raise MemoryWorkerUnavailable('Canonical memory generation is unavailable') from error

    def status(self):
        state=self.supervisor.snapshot() if self.supervisor else {'status':'not_started'}
        if state['status'] in ('needs_reconciliation','owner_busy','job_bound'):
            self._unavailable('needs_reconciliation')
        try:
            self._check_storage()
            records=self.queue.evidence_snapshot()['records'] if self.queue else []
            pending=sum(r['state'] in ('pending','working') for r in records)
            completed=sum(r['state']=='complete' for r in records)
        except (sqlite3.Error,OSError,ValueError,MemoryWorkerUnavailable):
            self._unavailable('storage_unavailable')
            state={'status':'storage_unavailable'};pending=completed=None
        status=self.recovery_status if self.recovery_status in ('storage_unavailable','worker_unavailable') else state['status']
        return {'ready':self.ready,'status':status,'pending':pending,
                'completed':completed,'backend':'hindsight_candidate',
                'recovery_status':self.recovery_status,'private_context_enabled':False}

    async def close(self):
        self.ready=False;self.incarnation=uuid4().hex
        if self.supervisor:
            await asyncio.to_thread(self.supervisor.stop);self.supervisor=None
        if self.worker:
            worker=self.worker;self.worker=None
            def stop():
                with self.lock:worker.stop()
            await asyncio.to_thread(stop)
        if self.gateway:await asyncio.to_thread(self.gateway.close);self.gateway=None
        if self.queue:self.queue.close();self.queue=None
        self.storage_identity=None
