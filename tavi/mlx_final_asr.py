"""Bounded synchronous adapter, owned by the existing recognizer thread.

The native child is killable on mute/timeout; every result remains lease-checked
by LiveWake. Startup/warmup happens before capture, not inside a final job.
"""
import base64
from contextlib import nullcontext
import json
import os
from pathlib import Path
import select
import subprocess
import threading
import time
from uuid import uuid4

from .asr_confidence import DecodedSpeech


class MlxFinalASR:
    def __init__(self, schedule=None, *, cache_mib=256, wired_mib=0, profile_stages=False, encoder_attention='standard'):
        if cache_mib not in (256,1024) or wired_mib not in (0,3072):
            raise ValueError('Unknown ASR memory configuration')
        self.cache_mib,self.wired_mib,self.profile_stages=cache_mib,wired_mib,profile_stages
        if encoder_attention not in ('standard','fused'):raise ValueError('Unknown encoder attention')
        self.encoder_attention=encoder_attention
        self.startup_timeout = 12
        self.schedule = schedule
        self.lock = threading.Lock()
        self.state = threading.Lock()
        self.process = None
        self.active = False
        self.inflight = False
        self.profile = None
        self.closed = False

    def _drop(self):
        with self.state:
            process, self.process = self.process, None
        if process:
            if process.poll() is None:
                try: process.kill()
                except ProcessLookupError: pass
            process.wait(timeout=1)
            process.stdin.close()
            process.stdout.close()

    def cancel(self):
        # No I/O lock or wait in the PCM/lease path. The reader reaps it.
        with self.state:
            if self.active and self.process and self.process.poll() is None:
                try: self.process.kill()
                except ProcessLookupError: pass

    def _read(self, process, deadline):
        data = bytearray()
        while len(data) <= 100_000:
            remaining = deadline-time.monotonic()
            if remaining <= 0 or not select.select([process.stdout], [], [], remaining)[0]:
                raise TimeoutError('Final ASR deadline exceeded')
            block = os.read(process.stdout.fileno(), 65536)
            if not block:
                raise ValueError('Final ASR worker ended')
            data.extend(block)
            if b'\n' in block:
                if not data.endswith(b'\n') or data.count(b'\n') != 1:
                    raise ValueError('Invalid ASR protocol framing')
                return json.loads(data)
        raise ValueError('Oversized ASR response')

    def _request(self, pcm, deadline):
        began=time.perf_counter()
        process = self.process
        request_id = uuid4().hex
        data = memoryview((json.dumps({'id': request_id,
                          'pcm': base64.b64encode(pcm).decode()})+'\n').encode())
        while data:
            remaining = deadline-time.monotonic()
            if remaining <= 0 or not select.select([], [process.stdin], [], remaining)[1]:
                raise TimeoutError('Final ASR deadline exceeded')
            try: written = os.write(process.stdin.fileno(), data)
            except BlockingIOError: continue
            data = data[written:]
        self.inflight = True
        try:
            result = self._read(process, deadline)
        finally:
            self.inflight = False
        if result.get('id') != request_id or 'error' in result:
            raise ValueError('Final ASR failed or returned an invalid ID')
        if not isinstance(result.get('text'), str) or not isinstance(result.get('confidence'), dict):
            raise ValueError('Invalid final ASR result')
        timing={**(result.get('timing') or {}),'IPC_roundtrip_ms':(time.perf_counter()-began)*1000}
        return DecodedSpeech(result['text'], result['confidence'],timing)

    def prepare(self):
        with self.lock:
            with self.state:
                if self.closed:
                    raise ValueError('Final ASR is closed')
            if self.process and self.process.poll() is None:
                return
            self._drop()
            root = Path(__file__).resolve().parent.parent
            env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'LANG': 'en_US.UTF-8',
                   'HF_HUB_OFFLINE': '1', 'HF_HUB_DISABLE_TELEMETRY': '1',
                   'HF_HUB_DISABLE_IMPLICIT_TOKEN': '1', 'TRANSFORMERS_OFFLINE': '1'}
            try:
                command=self.worker_command(root)
                child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, bufsize=0, env=env, cwd=root)
                with self.state:
                    self.process = child
                    if self.closed:
                        child.kill()
                        raise ValueError('Final ASR closed during preparation')
                os.set_blocking(self.process.stdin.fileno(), False)
                deadline = time.monotonic()+self.startup_timeout
                ready = self._read(self.process, deadline)
                if ready.get('ready') is not True or ready.get('protocol') != 1:
                    raise ValueError('Invalid final ASR startup')
                self.profile = ready['profile']
                self._request(bytes(32000), deadline)  # In-memory silence, discarded.
            except BaseException:
                self._drop()
                raise

    def worker_command(self, root):
        command=[str(root/'.venv-asr-mlx/bin/python'),'-m','tavi.mlx_asr_worker',
                 '--cache-mib',str(self.cache_mib),'--wired-mib',str(self.wired_mib),
                 '--encoder-attention',self.encoder_attention]
        if self.profile_stages:command.append('--profile-stages')
        return command

    def decode(self, pcm, deadline, valid=None):
        if not isinstance(pcm, bytes) or not 0 < len(pcm) <= 640000 or len(pcm) % 2:
            raise ValueError('Expected bounded mono 16 kHz PCM16')
        with self.lock:
            if not self.process or self.process.poll() is not None:
                raise ValueError('Final ASR is not ready; restart capture')
            with self.state:
                # The lease may have changed before this job entered native
                # work. Check under the same lock used by cancel(), so stop
                # either rejects this job here or kills its active child.
                if valid is not None and not valid():
                    raise ValueError('Obsolete final ASR job')
                self.active = True
            try:
                queued=time.perf_counter()
                context = self.schedule.final_asr(deadline) if self.schedule else nullcontext()
                with context:
                    acquired=time.perf_counter()
                    result=self._request(pcm, deadline)
                    return DecodedSpeech(result.text,result.confidence,
                        {**(result.timing or {}),'schedule_wait_ms':(acquired-queued)*1000})
            except BaseException:
                self._drop()
                raise
            finally:
                with self.state:
                    self.active = False

    def close(self):
        # Closing is terminal and also kills preparation. cancel() intentionally
        # retains an idle warm worker on mute, and cannot serve this purpose.
        with self.state:
            self.closed = True
            if self.process and self.process.poll() is None:
                try: self.process.kill()
                except ProcessLookupError: pass
        with self.lock:
            self._drop()
