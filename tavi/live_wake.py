"""Bounded local ASR experiment. Decoder work never runs in the PCM request path."""
from collections import deque
from dataclasses import dataclass
from pathlib import Path
import re
import threading
import time
from uuid import uuid4
from .asr_confidence import DecodedSpeech, segment_confidence
from .addressing import ADDRESS, NAME, corroborates_request

RATE = 16000
FRAME = 512
FIRST_PARTIAL = 10240  # 640 ms after VAD onset
PARTIAL_STEP = 7680   # 480 ms
SEARCH_LIMIT = 64000  # First four seconds; final decoding still gets the whole turn
END_SILENCE = 12800   # 800 ms
MAX_SAMPLES = 320000  # 20 seconds, including pre-roll
MAX_JOB_AGE = 3.0
MODES = {'hinted': 'Names: Tavi, Paprika.', 'unhinted': None}


class WhisperDecoder:
    def __init__(self,final_model='tiny.en',schedule=None):
        if final_model not in ('tiny.en','base.en','turbo-mlx'):raise ValueError('Unknown final transcription model')
        self.final_backend = None
        # This module sets offline/telemetry flags before importing faster-whisper.
        from .name_comparison import protocol, verify_model
        from faster_whisper import WhisperModel
        import numpy as np
        self.np = np
        plan, _ = protocol()
        root = Path('.tavi/models/whisper-tiny-en')
        verify_model(root, plan)
        self.options = plan['asr']
        from importlib.metadata import version
        self.profile = {'model': 'tiny.en', 'model_sha256': plan['model_files']['model.bin'],
                        'engine': 'faster-whisper', 'engine_version': version('faster-whisper'),
                        'ctranslate2_version': version('ctranslate2'),
                        'compute_type': 'int8', 'cpu_threads': 2, 'options': dict(self.options)}
        self.model = WhisperModel(str(root), device='cpu', compute_type='int8',
                                  cpu_threads=2, local_files_only=True)
        self.final_model,self.final_profile=self.model,self.profile
        if final_model=='base.en':
            import hashlib,json
            spec=json.loads(Path(__file__).with_name('web').joinpath('speech-check-protocol.json').read_text())['models']['base.en']
            for filename,digest in spec['files'].items():
                if hashlib.sha256((Path(spec['path'])/filename).read_bytes()).hexdigest()!=digest:
                    raise ValueError('Final ASR model missing or checksum changed')
            self.final_model=WhisperModel(spec['path'],device='cpu',compute_type='int8',cpu_threads=2,local_files_only=True)
            self.final_profile={**self.profile,'model':'base.en','model_sha256':spec['files']['model.bin']}
        elif final_model=='turbo-mlx':
            from .mlx_final_asr import MlxFinalASR
            self.final_backend=MlxFinalASR(schedule)
            self.final_profile={'model':'large-v3-turbo','engine':'mlx-whisper','prompt':None}
        self.profiles={'partial':self.profile,'final':self.final_profile}

    def prepare(self):
        if self.final_backend:
            self.final_backend.prepare()
            self.final_profile=self.final_backend.profile
            self.profiles['final']=self.final_profile

    def cancel(self):
        if self.final_backend:self.final_backend.cancel()

    def close(self):
        if self.final_backend:self.final_backend.close()

    def decode(self, pcm, prompt):
        return self._decode(self.model,self.profile,pcm,prompt)

    def decode_final(self,pcm,prompt):
        if self.final_backend:
            return self.final_backend.decode(pcm,time.monotonic()+MAX_JOB_AGE)
        return self._decode(self.final_model,self.final_profile,pcm,prompt)

    def decode_final_job(self,pcm,prompt,deadline,valid=None):
        if self.final_backend:return self.final_backend.decode(pcm,deadline,valid)
        return self.decode_final(pcm,prompt)

    def verify_address(self,pcm,final_text,prompt=None):
        # A full-window decode can disprove a misleading tiny prefix. Preserve
        # the existing names-only prompt; never supply the expected request.
        # Only used for a missing final name after an anchored early address.
        started=time.monotonic()
        result=self.decode(pcm,prompt)
        return {'confirmed':corroborates_request(final_text,result.text),
                'method':'full_utterance_exact_body',
                'name_at_start':bool(ADDRESS.match(result.text)),
                'decode_ms':(time.monotonic()-started)*1000,
                'confidence':result.confidence}

    def _decode(self,model,profile,pcm,prompt):
        audio = self.np.frombuffer(pcm, dtype='<i2').astype(self.np.float32) / 32768
        segments, _ = model.transcribe(audio, initial_prompt=prompt, **self.options)
        # Fully consume the iterator in the worker, not the HTTP frame handler.
        decoded = list(segments)
        return DecodedSpeech(' '.join(s.text for s in decoded).strip()[:2000],
                             {**segment_confidence(decoded), 'decoder': profile,
                              'prompt': prompt})


@dataclass(frozen=True)
class Job:
    lease: str
    utterance: int
    final: bool
    pcm: bytes
    prompt: str | None
    onset: int
    snapshot_end: int
    queued_at: float


class LiveWake:
    """One capture lease, one running decode, at most one pending snapshot.

    Old partial snapshots may be replaced by newer ones. Finals take priority;
    two pending finals fail closed rather than silently dropping requests.
    """
    def __init__(self, detector, decoder, clock=time.monotonic, *, identity_observer=None):
        self.detector, self.decoder, self.clock = detector, decoder, clock
        self.identity_observer = identity_observer
        self.condition = threading.Condition(threading.RLock())
        self.stream_id = None
        self.pending = self.running = None
        self.closing = False
        self.events = deque()
        self._clear()
        self.thread = threading.Thread(target=self._work, name='paprika-local-asr', daemon=True)
        self.thread.start()

    def _clear(self):
        self.preroll = deque(maxlen=10)  # 320 ms, overwritten while idle
        self.segment = None
        self.sequence = -1
        self.high = self.utterance = self.replaced = 0
        self.onset = self.segment_start = self.last_speech_end = self.next_partial = 0
        self.last = self.clock()
        self.acknowledged = set()
        self.address_prefixes = set()
        self.fault = None
        self.events.clear()
        self.detector.reset()

    def _stop(self):
        self.stream_id = None
        self.pending = None
        if hasattr(self.decoder,'cancel'):self.decoder.cancel()
        if self.identity_observer:self.identity_observer.reset(None)
        self._clear()
        self.condition.notify_all()

    def start(self, mode):
        if mode not in MODES:
            raise ValueError('Choose hinted or unhinted mode')
        with self.condition:
            if self.closing:
                raise ValueError('Local recognizer is shutting down')
            if self.running and self.clock() - self.running.queued_at > MAX_JOB_AGE:
                raise ValueError('Local recognizer is still busy; the local service needs a restart')
            self._stop()
        # Warm the killable final worker before granting a microphone lease.
        # Native initialization must not consume a three-second request budget.
        if hasattr(self.decoder,'prepare'):self.decoder.prepare()
        with self.condition:
            if self.closing:raise ValueError('Local recognizer is shutting down')
            self.mode = mode
            self.last = self.clock()  # Startup/warmup is outside capture time.
            self.stream_id = uuid4().hex
            if self.identity_observer:self.identity_observer.reset(self.stream_id)
            self.asr_run_id = uuid4().hex
            return {'stream_id': self.stream_id, 'sample_rate': RATE, 'frame_samples': FRAME,
                    'asr_run_id': self.asr_run_id,
                    'mode': mode, 'target': 'paprika', 'cloud_enabled': False,
                    'recognition_models':getattr(self.decoder,'profiles',None),
                    'first_partial_ms': 640, 'partial_step_ms': 480, 'endpoint_silence_ms': 800,
                    'max_utterance_seconds': 20}

    def stop(self, lease):
        with self.condition:
            if lease == self.stream_id:
                self._stop()
            return {'stopped': True}

    def expire(self):
        with self.condition:
            if self.stream_id and self.clock() - self.last > 2:
                self._stop()

    def close(self):
        with self.condition:
            self._stop()
            self.closing = True
            self.condition.notify_all()
        self.thread.join(timeout=1)
        if hasattr(self.decoder,'close'):self.decoder.close()

    def _emit(self, event):
        if len(self.events) >= 64:
            self.fault = 'Recognition event backlog; restart capture'
            return
        self.events.append(event)

    def _submit(self, final, end):
        if self.pending and self.pending.final:
            if not final:
                return
            self.fault = 'Recognition overloaded; a final request is still queued'
            return
        if self.pending:
            self.replaced += 1
        # Preserve pre-roll in the turn buffer; crop only the ASR input as in
        # the offline comparison (100 ms before VAD onset, 200 ms after speech).
        start = max(0, self.onset - 1600 - self.segment_start)
        stop = min(end, self.last_speech_end + 3200) if final else end
        pcm = b''.join(self.segment)[start * 2:(stop - self.segment_start) * 2]
        self.pending = Job(self.stream_id, self.utterance, final, pcm, MODES[self.mode],
                           self.onset, stop, self.clock())
        if final and self.identity_observer:self.identity_observer.submit(self.stream_id,self.utterance,pcm)
        self.condition.notify()

    def feed(self, lease, sequence, pcm):
        with self.condition:
            if self.stream_id is None or lease != self.stream_id:
                raise ValueError('Live microphone lease expired')
            if self.fault:
                message = self.fault
                self._stop()
                raise ValueError(message)
            if any(job and job.lease == self.stream_id and self.clock() - job.queued_at > MAX_JOB_AGE
                   for job in (self.running, self.pending)):
                self._stop()
                raise ValueError('Local recognition exceeded its three-second age limit')
            if self.clock() - self.last > 2 or type(sequence) is not int or sequence != self.sequence + 1 or len(pcm) != 1024:
                self._stop()
                raise ValueError('Audio gap, stale input or invalid PCM; restart capture')
            probability = self.detector.probability(pcm)
            self.sequence, self.last = sequence, self.clock()
            end = (sequence + 1) * FRAME
            self.preroll.append(pcm)
            self.high = self.high + 1 if probability >= .5 else 0
            if self.segment is None and self.high >= 2:
                self.utterance += 1
                self.segment = list(self.preroll)
                self.segment_start = end - len(self.segment) * FRAME
                self.onset = max(0, (sequence - 1) * FRAME)
                self.next_partial = self.onset + FIRST_PARTIAL
                self.last_speech_end = end
                self._emit({'type': 'speech_started', 'utterance': self.utterance,
                            'speech_onset_sample': self.onset, 'buffer_start_sample': self.segment_start})
            elif self.segment is not None:
                self.segment.append(pcm)
            if self.segment is not None:
                if probability >= .5:
                    self.last_speech_end = end
                if end - self.segment_start > MAX_SAMPLES:
                    self._stop()
                    raise ValueError('Speech exceeded the 20-second test limit; restart capture')
                if end - self.last_speech_end >= END_SILENCE:
                    self._submit(True, end)
                    self._emit({'type': 'speech_ended', 'utterance': self.utterance,
                                'speech_end_sample': self.last_speech_end,
                                'retained_samples': end - self.segment_start,
                                'buffer_start_sample': self.segment_start})
                    self.segment = None
                elif (end >= self.next_partial and end - self.onset <= SEARCH_LIMIT
                      and self.utterance not in self.acknowledged):
                    self._submit(False, end)
                    self.next_partial = end + PARTIAL_STEP
            if self.fault:
                message = self.fault
                self._stop()
                raise ValueError(message)
            events = list(self.events)
            self.events.clear()
            return {'sequence': sequence, 'probability': probability, 'speech': self.segment is not None,
                    'utterance': self.utterance, 'buffered_ms': len(self.segment or ()) * 32,
                    'decode_running': self.running is not None, 'decode_pending': self.pending is not None,
                    'partial_snapshots_replaced': self.replaced, 'events': events}

    def _work(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closing or self.pending is not None)
                if self.closing:
                    return
                job = self.pending
                self.pending = None
                self.running = job
            started = self.clock()
            try:
                if job.final and hasattr(self.decoder,'decode_final_job'):
                    decoded=self.decoder.decode_final_job(job.pcm,job.prompt,job.queued_at+MAX_JOB_AGE,
                                                         lambda:job.lease==self.stream_id)
                else:
                    decode=self.decoder.decode_final if job.final and hasattr(self.decoder,'decode_final') else self.decoder.decode
                    decoded = decode(job.pcm, job.prompt)
                if isinstance(decoded, DecodedSpeech):
                    text, confidence = decoded.text, decoded.confidence
                    timing=decoded.timing
                else:
                    text, confidence = decoded, None  # Explicitly unscored test/alternate decoder.
                    timing=None
                verification=None
                with self.condition:
                    verify=(job.final and job.lease==self.stream_id
                            and job.utterance in self.address_prefixes and not NAME.search(text)
                            and bool(text.strip()) and hasattr(self.decoder,'verify_address'))
                if verify:
                    verification=self.decoder.verify_address(job.pcm,text,job.prompt)
                error = None
            except Exception as exc:
                text, error = '', 'Local speech recognition failed (' + type(exc).__name__ + ')'
            ended = self.clock()
            with self.condition:
                self.running = None
                self.condition.notify_all()
                if job.lease != self.stream_id:
                    continue  # Muted/replaced lease: never publish a late result.
                if error or ended - job.queued_at > MAX_JOB_AGE:
                    self.fault = error or 'Local recognition exceeded its three-second age limit'
                    self.pending = None
                    continue
                matched = bool(re.search(r'\bpaprika\b', text, re.IGNORECASE))
                first = matched and job.utterance not in self.acknowledged
                if first:
                    self.acknowledged.add(job.utterance)
                    if len(self.acknowledged) > 64:
                        self.acknowledged.remove(min(self.acknowledged))
                if not job.final and ADDRESS.match(text):
                    self.address_prefixes.add(job.utterance)
                    if len(self.address_prefixes)>64:self.address_prefixes.remove(min(self.address_prefixes))
                self._emit({'type': 'recognition', 'utterance': job.utterance, 'final': job.final,
                            'asr_run_id': self.asr_run_id, 'recognition_id': uuid4().hex,
                            'confidence': confidence,
                            'worker_timing': timing,
                            'address_verification':verification,
                            'text': text, 'name_match': matched, 'first_detection': first,
                            'heard_name_any': job.utterance in self.acknowledged,
                            'speech_onset_sample': job.onset, 'snapshot_end_sample': job.snapshot_end,
                            'audio_start_sample': job.snapshot_end-len(job.pcm)//2,
                            'audio_samples': len(job.pcm)//2,
                            'decode_ms': (ended - started) * 1000,
                            'job_age_ms': (ended-job.queued_at)*1000,
                            'deadline_remaining_ms': (MAX_JOB_AGE-ended+job.queued_at)*1000,
                            'queue_wait_ms': (started - job.queued_at) * 1000})
