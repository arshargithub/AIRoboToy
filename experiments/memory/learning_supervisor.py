"""One owned background ingestion worker; no automatic retries of ambiguity.

Native requests never run on the conversation loop. A process-level lock stops
second supervisors; orphaned working jobs require explicit reconciliation.
"""
import fcntl,threading,time
from pathlib import Path
from experiments.memory.learning_queue import LearningQueue

class LearningSupervisor:
    def __init__(self,path,client_factory, *, maximum_jobs=16):
        self.path=Path(path);self.factory=client_factory;self.maximum_jobs=maximum_jobs
        self.wake=threading.Event();self.stopping=threading.Event();self.aborting=threading.Event()
        self.lock=threading.Lock();self.thread=None;self.client=None
        self.state={'status':'not_started','completed':0,'failed':0,'late_blocked':0,'events':[]}
    def _update(self,**fields):
        with self.lock:self.state.update(fields)
    def snapshot(self):
        from copy import deepcopy
        with self.lock:return deepcopy(self.state)
    def start(self):
        if self.thread is not None:raise ValueError('Supervisor already started')
        self.thread=threading.Thread(target=self._run,name='paprika-learning',daemon=True);self.thread.start()
    def notify(self):self.wake.set()
    def _run(self):
        queue=None;owner=None;locked=False;job=None
        try:
            owner=open(str(self.path)+'.owner','a')
            fcntl.flock(owner,fcntl.LOCK_EX|fcntl.LOCK_NB);locked=True
            queue=LearningQueue(self.path)
            if queue.working():
                self._update(status='needs_reconciliation');return
            self.client=self.factory()
            if self.stopping.is_set():return
            self.client.initialize();self._update(status='idle')
            while not self.stopping.is_set():
                self.wake.clear();job=queue.claim()
                if job is None:
                    self.wake.wait(.2);continue
                if self.snapshot()['completed']>=self.maximum_jobs:
                    # No dispatch, but retain durable owned job for explicit
                    # reconciliation instead of silently exceeding the bound.
                    self._update(status='job_bound');return
                self._update(status='working',active_job=job);start=time.monotonic()
                if not queue.note_work(job,'dispatched'):
                    self._update(status='idle',active_job=None);continue
                result=self.client.ingest(job['source'])
                if self.aborting.is_set():
                    queue.note_work(job,'aborted');return
                accepted=queue.complete(job)
                with self.lock:
                    self.state['completed']+=int(accepted);self.state['late_blocked']+=int(not accepted)
                    self.state['events']=(self.state['events']+[{'source_id':job['source']['id'],'accepted':accepted,'elapsed_ms':(time.monotonic()-start)*1000,'native':result}])[-32:]
                    self.state.update(status='idle',active_job=None)
        except BlockingIOError:self._update(status='owner_busy')
        except Exception as error:
            # Remote success may be unknown. Leave the claim intact and do not
            # dispatch another job or retry this one automatically.
            if queue and job:
                try:queue.note_work(job,'aborted' if self.aborting.is_set() else 'ambiguous')
                except Exception as timing_error:
                    # Preserve original ambiguity and expose missing evidence.
                    self._update(timing_error_type=type(timing_error).__name__)
            self._update(status='needs_reconciliation',failed=1,error_type=type(error).__name__)
        finally:
            if self.client:
                try:self.client.close()
                except Exception as error:self._update(close_error_type=type(error).__name__)
            if queue:queue.close()
            if locked:fcntl.flock(owner,fcntl.LOCK_UN)
            if owner:owner.close()
            if self.stopping.is_set():self._update(stopped=True)
    def stop(self, *, abort=True, timeout=5):
        self.stopping.set();self.wake.set()
        if abort:
            self.aborting.set()
            if self.client:self.client.abort()
        if self.thread:self.thread.join(timeout)
        if self.thread and self.thread.is_alive():raise TimeoutError('Learning owner has not stopped; do not recover its job')

class NativeLearningClient:
    def __init__(self,directory,logs,people,*,source_realm=None):
        from experiments.memory.pilot import Process
        self.worker=Process('hindsight',directory,logs,'learning_worker.py',**({'source_realm':source_realm} if source_realm else {}));self.people=people
    def _send(self,request):
        value=self.worker.send(request,timeout=45)
        if not value['ok']:raise RuntimeError('Native learning operation failed')
        return value['result']
    def initialize(self):return self._send({'op':'initialize'})
    def ingest(self,source):return self._send({'op':'ingest','episode':source,'people':self.people})
    def abort(self):
        if self.worker.process.poll() is None:self.worker.process.kill()
    def close(self):self.worker.stop()
