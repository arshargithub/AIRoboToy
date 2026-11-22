"""Owned stdio channel. A timed-out reply cannot answer a later request.

Retiring the local child does not prove a remote operation was cancelled.
Callers must retain ambiguous writes/reservations; this module never retries.
"""
import json
import math
import os
import selectors
import subprocess
import threading
import time


class MemoryWorkerUnavailable(RuntimeError):
    code = 'memory_worker_unavailable'
    user_message = 'Memory is unavailable'
    recovery = 'Stop and save this attempt before trying again.'


class MemoryWorkerTimeout(TimeoutError):
    code = MemoryWorkerUnavailable.code
    user_message = MemoryWorkerUnavailable.user_message
    recovery = MemoryWorkerUnavailable.recovery


class WorkerTransport:
    def __init__(self, process, log, engine):
        self.process, self.log, self.engine = process, log, engine
        self.buffer = b''
        self.unusable = False
        self.closed = False
        self._sending = threading.Lock()

    def _retire(self):
        self.unusable = True
        self.buffer = b''
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=2)

    def send(self, request, timeout=420, expect_crash=False):
        # Invalid local arguments cannot dispatch or poison a healthy channel.
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('Positive finite worker timeout required')
        raw = (json.dumps(request)+'\n').encode()
        if not self._sending.acquire(blocking=False):
            raise RuntimeError('Memory worker already has an outstanding request')
        try:
            if self.closed or self.unusable:
                raise MemoryWorkerUnavailable('Memory worker retired; do not reuse or automatically retry')
            try:
                return self._exchange(raw, timeout, expect_crash, request)
            except TimeoutError as error:
                self._retire()
                raise MemoryWorkerTimeout(self.engine+' worker timed out; completion is uncertain') from error
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                self._retire()
                raise MemoryWorkerUnavailable(self.engine+' worker channel failed; completion is uncertain') from error
        finally:
            self._sending.release()

    def _exchange(self, raw, timeout, expect_crash, request):
        deadline = time.monotonic()+timeout
        self.process.stdin.write(raw)
        self.process.stdin.flush()
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            while time.monotonic() < deadline:
                if b'\n' not in self.buffer:
                    events = selector.select(min(1, max(0, deadline-time.monotonic())))
                    if not events:continue
                    chunk = os.read(self.process.stdout.fileno(), 65536)
                    if not chunk:
                        code = self.process.wait(timeout=2)
                        if expect_crash and code == 78:
                            self.unusable = True
                            return {'ok': True, 'result': {'injected_exit': 78,
                                'boundary': request.get('crash', 'after durable ledger, before native dispatch')}}
                        raise RuntimeError('Memory worker exited before acknowledging its request')
                    self.buffer += chunk
                    continue
                line, self.buffer = self.buffer.split(b'\n', 1)
                try:result = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    self.log.write(line.decode(errors='replace')+'\n');self.log.flush()
                    continue
                if isinstance(result, dict) and 'ok' in result:
                    if (type(result['ok']) is not bool or
                        (result['ok'] and 'result' not in result) or
                        (not result['ok'] and not isinstance(result.get('error'), str))):
                        raise ValueError('Malformed memory response envelope')
                    return result
        raise TimeoutError('Memory worker deadline exceeded')

    def stop(self):
        if self.closed:return
        try:
            if self.process.poll() is None and not self.unusable and not self._sending.locked():
                try:self.send({'op': 'close'}, timeout=25)
                except Exception:pass
            if self.process.poll() is None:
                self._retire()
            else:self.process.wait(timeout=2)
        finally:
            self.closed = True
            self.unusable = True
            for stream in (self.process.stdin, self.process.stdout):
                if stream:stream.close()
            self.log.close()
