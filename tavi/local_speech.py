"""Persistent isolated local speech worker; whole WAV publication preserves ACKs.

Model inference never runs on the capture/controller event loop. Cancellation
kills the worker rather than leaving unbounded native work running in a thread.
The next request starts a fresh, bounded worker. Nothing is written to disk.
"""
import asyncio
import base64
from io import BytesIO
import json
import os
from pathlib import Path
import sys
from uuid import uuid4
import wave

from .conversation_providers import Speech
from .speech_errors import SpeechWorkerError


def validate_wave(data, sample_rate=22050):
    if sample_rate not in (22050,24000):raise ValueError('Unknown local voice sample rate')
    if not isinstance(data, bytes) or len(data) > 1_500_000:
        raise ValueError('Local voice audio exceeds its bound')
    with wave.open(BytesIO(data)) as audio:
        if (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) != (sample_rate, 1, 2):
            raise ValueError('Unexpected local voice format')
        frames = audio.getnframes()
        if not 0 < frames <= sample_rate*30 or len(audio.readframes(frames)) != frames*2:
            raise ValueError('Invalid or oversized local voice audio')
    return Speech(data, (frames*1000+sample_rate-1)//sample_rate)


class LocalSpeech:
    name = 'Piper · LJ Speech (local)'

    def __init__(self, backend='piper'):
        if backend not in ('piper','kokoro-k','kokoro-k-mlx'):raise ValueError('Unknown local voice backend')
        self.backend=backend
        self.sample_rate=24000 if backend.startswith('kokoro-k') else 22050
        if backend.startswith('kokoro-k'):self.name='K · Kokoro 35% donor (local'+(' MLX' if backend.endswith('-mlx') else '')+', provisional)'
        self.process = None
        self.lock = asyncio.Lock()
        self.inflight = False

    async def _drop(self):
        process, self.process = self.process, None
        if process is not None:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            await process.wait()

    async def _prepare(self):
        if self.process is not None and self.process.returncode is None:
            return
        await self._drop()
        executable=str(Path(__file__).resolve().parent.parent/'.venv-k-speech/bin/python') if self.backend=='kokoro-k-mlx' else sys.executable
        self.process = await asyncio.create_subprocess_exec(
            executable, '-m', 'tavi.local_speech_worker', '--backend', self.backend,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, limit=2_000_000,
            env={'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'LANG': 'en_US.UTF-8',
                 'HF_HUB_OFFLINE': '1', 'HF_HUB_DISABLE_TELEMETRY': '1'})
        line = await asyncio.wait_for(self.process.stdout.readline(), 12)
        if not line:raise SpeechWorkerError('worker_ended')
        try:ready=json.loads(line)
        except json.JSONDecodeError:raise SpeechWorkerError('invalid_response') from None
        if ready != {'ready': True, 'protocol': 1}:raise SpeechWorkerError('initialization_failed')

    async def prepare(self):
        async with self.lock:
            try:
                await self._prepare()
            except BaseException:
                await self._drop()
                raise

    async def synthesize(self, text):
        if not isinstance(text, str) or not 0 < len(text) <= 480:
            raise ValueError('Reply exceeds local voice text bound')
        async with self.lock:
            try:
                await self._prepare()
                request_id = uuid4().hex
                self.process.stdin.write((json.dumps({'id': request_id, 'text': text})+'\n').encode())
                await self.process.stdin.drain()
                self.inflight = True
                line = await asyncio.wait_for(self.process.stdout.readline(), 16 if self.backend.startswith('kokoro-k') else 8)
                if not line:raise SpeechWorkerError('worker_ended')
                try:result=json.loads(line)
                except json.JSONDecodeError:raise SpeechWorkerError('invalid_response') from None
                if isinstance(result,dict) and result.get('id')==request_id and set(result)=={'id','error'}:
                    raise SpeechWorkerError(result['error'])
                if not isinstance(result,dict) or result.get('id') != request_id or set(result) != {'id', 'wav'}:
                    raise ValueError('Local voice worker returned an invalid response')
                return validate_wave(base64.b64decode(result['wav'], validate=True), self.sample_rate)
            except BaseException:
                await self._drop()
                raise
            finally:
                self.inflight = False

    async def close(self):
        async with self.lock:
            await self._drop()
