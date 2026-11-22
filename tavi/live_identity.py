"""Bounded parallel local scoring. No PCM, voice vector or identity goes cloud.

The ASR path never waits for this worker. Late/missing evidence stays unknown;
the host can latch a result once at final text acceptance, never retrospectively.
"""
from collections import deque
from dataclasses import dataclass
import hashlib
import queue
import threading
import time
from tavi.speaker_evidence import TurnKey,compare_shadow


@dataclass(frozen=True)
class VoiceDecision:
    speaker_id:str
    reason:str
    turn:object=None
    profiles_revision:str=''
    policy_revision:str=''


class LiveIdentity:
    def __init__(self,catalog,encoder,model_sha256,*,policy=None,clock=time.monotonic):
        self.catalog,self.encoder,self.model_sha256=catalog,encoder,model_sha256
        self.policy=policy;self.clock=clock;self.lock=threading.Lock();self.jobs=queue.Queue(maxsize=1)
        self.lease=None;self.epoch=0;self.results={};self.metrics=deque(maxlen=64);self.closed=False;self.running=False
        self.thread=threading.Thread(target=self._work,name='paprika-voice-score',daemon=True);self.thread.start()

    def prepare(self):
        # Prewarm before capture, not on its32ms acknowledgement path.
        with self.encoder.lock:self.encoder.prepare()

    def reset(self,lease):
        with self.lock:
            self.epoch+=1;self.lease=lease;self.results.clear();running=self.running
            try:
                while True:self.jobs.get_nowait()
            except queue.Empty:pass
        if running and hasattr(self.encoder,'cancel'):self.encoder.cancel()

    def submit(self,lease,utterance,pcm):
        with self.lock:
            if self.closed or lease!=self.lease:return
            job=(self.epoch,lease,utterance,pcm,self.catalog.revision,self.clock())
            try:self.jobs.put_nowait(job)
            except queue.Full:self.metrics.append({'reason':'voice_backlog_unknown'})

    def _work(self):
        while True:
            job=self.jobs.get()
            if job is None:return
            epoch,lease,utterance,pcm,revision,issued=job
            with self.lock:
                if epoch!=self.epoch or lease!=self.lease or self.closed:continue
                self.running=True
            try:
                # The first bounded window is deterministic; not selected by a desired match.
                window=pcm[:256000]
                encoded=self.encoder.encode(window)
                if (encoded['pcm_sha256']!=hashlib.sha256(window).hexdigest() or encoded['model_sha256']!=self.model_sha256
                    or encoded.get('dimension')!=512 or encoded.get('quality',{}).get('voiced_seconds',0)<2):raise ValueError('Unbound or insufficient speaker result')
                turn=TurnKey(lease,str(utterance),hashlib.sha256(pcm).hexdigest(),epoch)
                evidence=compare_shadow(turn,encoded['embedding'],self.model_sha256,self.catalog.candidates,quality_eligible=True)
                decision='unknown';reason=evidence.reason;policy_revision=''
                if self.policy and self.policy.profiles_revision==revision and self.policy.model_sha256==self.model_sha256:
                    from tavi.identity_policy import rank
                    decision=rank([{'person_id':s.person_id,'cosine':s.cosine} for s in evidence.scores],self.policy.threshold,self.policy.margin,eligible=True)
                    reason='qualified_match' if decision!='unknown' else 'uncertain_match';policy_revision=self.policy.certificate_sha256
                result=VoiceDecision(decision,reason,turn,revision,policy_revision)
            except Exception:
                result=VoiceDecision('unknown','quality_or_worker_unavailable',profiles_revision=revision)
            finally:
                with self.lock:self.running=False
            with self.lock:
                if epoch!=self.epoch or lease!=self.lease or self.closed:continue
                if self.clock()-issued>3:result=VoiceDecision('unknown','voice_result_late',profiles_revision=revision)
                self.results[(lease,utterance)]=result
                while len(self.results)>32:del self.results[next(iter(self.results))]
                self.metrics.append({'reason':result.reason,'elapsed_ms':round((self.clock()-issued)*1000,1)})

    def latch(self,lease,utterance):
        with self.lock:
            result=self.results.pop((lease,utterance),None)
            if lease!=self.lease:return VoiceDecision('unknown','stale_lease')
        if not self.catalog.current():return VoiceDecision('unknown','profiles_or_storage_changed')
        if result is None:return VoiceDecision('unknown','voice_not_ready')
        if result.profiles_revision!=self.catalog.revision:return VoiceDecision('unknown','profiles_changed')
        return result

    def close(self):
        with self.lock:
            if self.closed:return
        self.reset(None)
        with self.lock:self.closed=True
        try:self.jobs.put_nowait(None)
        except queue.Full:raise RuntimeError('Voice owner did not clear its pending work')
        self.thread.join(timeout=3)
        if self.thread.is_alive():raise TimeoutError('Voice owner did not stop')
        self.encoder.close()
