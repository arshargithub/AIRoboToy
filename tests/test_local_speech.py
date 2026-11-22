import asyncio
import base64
from io import BytesIO
import json
import os
import unittest
from unittest.mock import patch
import wave

from tavi.local_speech import LocalSpeech, validate_wave
from tavi.speech_errors import SpeechWorkerError


def wav(rate=22050, frames=100):
    out = BytesIO()
    with wave.open(out, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(bytes(frames*2))
    return out.getvalue()


class Process:
    def __init__(self, *, hold=False, mismatch=False, rate=22050):
        self.stdout = self; self.stdin = self; self.returncode = None
        self.lines = asyncio.Queue(); self.lines.put_nowait(b'{"ready":true,"protocol":1}\n')
        self.hold, self.mismatch = hold, mismatch
        self.rate=rate
        self.requests = []; self.killed = False

    async def readline(self): return await self.lines.get()
    async def drain(self): pass
    async def wait(self): return self.returncode
    def kill(self): self.killed = True; self.returncode = -9
    def write(self, raw):
        request = json.loads(raw); self.requests.append(request)
        if not self.hold:
            self.lines.put_nowait(json.dumps({'id': 'wrong' if self.mismatch else request['id'],
                                             'wav': base64.b64encode(wav(rate=self.rate)).decode()}).encode()+b'\n')


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_structured_error_and_eof_are_not_json_decode_failures(self):
        for output,code in [('error','unsupported_phoneme'),('eof','worker_ended')]:
            process=Process()
            def write(raw):
                request=json.loads(raw)
                process.lines.put_nowait(b'' if output=='eof' else json.dumps({'id':request['id'],'error':'unsupported_phoneme'}).encode()+b'\n')
            process.write=write
            async def spawn(*args,**kwargs):return process
            voice=LocalSpeech()
            with patch('asyncio.create_subprocess_exec',spawn):
                with self.assertRaises(SpeechWorkerError) as caught:await voice.synthesize('A synthetic request.')
            self.assertEqual(caught.exception.code,code);self.assertTrue(process.killed)

    async def test_accelerated_worker_uses_its_isolated_interpreter(self):
        process=Process(rate=24000);calls=[]
        async def spawn(*args,**kwargs):calls.append((args,kwargs));return process
        voice=LocalSpeech('kokoro-k-mlx')
        with patch('asyncio.create_subprocess_exec',spawn):await voice.synthesize('A local test.')
        self.assertTrue(calls[0][0][0].endswith('/.venv-k-speech/bin/python'))
        self.assertEqual(calls[0][0][-1],'kokoro-k-mlx');self.assertIn('MLX',voice.name)
        self.assertNotIn('OPENAI_API_KEY',calls[0][1]['env']);await voice.close()

    async def test_k_worker_selection_metadata_and_sample_rate(self):
        process=Process(rate=24000);calls=[]
        async def spawn(*args,**kwargs):calls.append((args,kwargs));return process
        voice=LocalSpeech('kokoro-k')
        with patch('asyncio.create_subprocess_exec',spawn):
            speech=await voice.synthesize('Paprika is ready.')
        self.assertEqual(calls[0][0][-2:],('--backend','kokoro-k'))
        self.assertIn('provisional',voice.name);self.assertGreater(speech.duration_ms,0)
        self.assertNotIn('OPENAI_API_KEY',calls[0][1]['env'])
        await voice.close()
        with self.assertRaises(ValueError):validate_wave(wav(),24000)
        self.assertGreater(validate_wave(wav(rate=24000),24000).duration_ms,0)

    async def test_warm_worker_is_reused_and_does_not_inherit_credentials(self):
        process = Process(); calls = []
        async def spawn(*args, **kwargs): calls.append((args, kwargs)); return process
        voice = LocalSpeech()
        with patch('asyncio.create_subprocess_exec', spawn), patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-secret'}):
            await voice.prepare()
            first = await voice.synthesize('A fictional test.')
            await voice.synthesize('Another fictional test.')
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(process.requests), 2)
        self.assertNotIn('OPENAI_API_KEY', calls[0][1]['env'])
        self.assertNotIn('A fictional test.', str(calls[0][0]))
        self.assertGreater(first.duration_ms, 0)
        await voice.close(); self.assertTrue(process.killed)

    async def test_cancel_kills_inflight_native_work_then_next_request_is_fresh(self):
        old, new = Process(hold=True), Process(); workers = iter([old, new])
        async def spawn(*args, **kwargs): return next(workers)
        voice = LocalSpeech()
        with patch('asyncio.create_subprocess_exec', spawn):
            task = asyncio.create_task(voice.synthesize('Old reply.'))
            for _ in range(8): await asyncio.sleep(0)
            self.assertEqual(len(old.requests), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
            self.assertTrue(old.killed); self.assertIsNone(voice.process)
            await voice.synthesize('New reply.')
            self.assertNotEqual(old.requests[0]['id'], new.requests[0]['id'])
        await voice.close()

    async def test_mismatched_response_fails_closed_without_retry(self):
        process = Process(mismatch=True); count = 0
        async def spawn(*args, **kwargs):
            nonlocal count
            count += 1; return process
        voice = LocalSpeech()
        with patch('asyncio.create_subprocess_exec', spawn):
            with self.assertRaises(ValueError): await voice.synthesize('A fictional test.')
        self.assertEqual(count, 1); self.assertTrue(process.killed)

    async def test_text_and_audio_bounds(self):
        voice = LocalSpeech()
        for text in ['', 'x'*481, None]:
            with self.assertRaises(ValueError): await voice.synthesize(text)
        self.assertIsNone(voice.process)
        for data in [wav(rate=16000), wav(frames=0), wav(frames=22050*30+1)]:
            with self.assertRaises(ValueError): validate_wave(data)
        self.assertGreater(validate_wave(wav()).duration_ms, 0)


if __name__ == '__main__': unittest.main()
