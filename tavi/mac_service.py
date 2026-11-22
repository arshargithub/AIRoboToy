"""Authenticated loopback core for the Mac app. No auto capture or inference.

The desktop owns credentials and the current audio endpoint, not the renderer.
Existing labs and their defaults are unaffected. This is not a LAN listener.
"""
import argparse
import asyncio
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import signal
import threading
from uuid import uuid4

from tavi.companion_text import conversation
from tavi.service import Demo, LocalHTTPServer, handler_for
from tavi.storage import Store, APPROVED_BUDGET_MICRO_USD

ROOT = Path(__file__).resolve().parent.parent
PROTOCOL = 1
CONSENT = 'mac-local-speech-transactional-text-v1'
ASSETS = {'/': ('companion.html', 'text/html; charset=utf-8'),
          '/family-voices': ('voice-calibration.html', 'text/html; charset=utf-8'),
          '/voice-calibration.js': ('voice-calibration.js', 'text/javascript'),
          '/voice-calibration.css': ('voice-calibration.css', 'text/css'),
          '/companion.js': ('companion.js', 'text/javascript'),
          '/companion.css': ('companion.css', 'text/css'),
          '/mac-audio-endpoint.js': ('mac-audio-endpoint.js', 'text/javascript'),
          '/mac-check-guide.js': ('mac-check-guide.js', 'text/javascript'),
          '/companion-state.js': ('companion-state.js', 'text/javascript'),
          '/capture.js': ('capture.js', 'text/javascript'),
          '/interruption.js': ('interruption.js', 'text/javascript'),
          '/chunk-audio-prefetch.js': ('chunk-audio-prefetch.js', 'text/javascript')}
POSTS = {'start', 'stop', 'frame', 'started', 'played', 'interrupt', 'end', 'online'}


def prerequisites():
    from experiments.memory.runtime import SSD
    required = [ROOT/'.venv-asr-mlx/bin/python', ROOT/'.venv-k-speech/bin/python',
                ROOT/'.tavi/models/silero_vad.onnx', ROOT/'.tavi/models/whisper-tiny-en/model.bin']
    drive = SSD.parent.is_mount()
    local = all(p.is_file() for p in required)
    from tavi.conversation_providers import runtime_key
    try: runtime_key(); key = True
    except ValueError: key = False
    return {'drive': drive, 'local_files': local, 'cloud_key': key,
            'ready': drive and local, 'memory_enabled': False, 'recognition_enabled': False}


def handler(base, loop, store, port, token, instance, *, readiness=prerequisites,household=None,calibration=None):
    class Handler(base):
        def reply(self, status, data, content_type='application/json'):
            payload = data if isinstance(data, bytes) else json.dumps(data).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Permissions-Policy', 'microphone=(self), camera=(), geolocation=()')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'none'; media-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            if status >= 400:
                self.close_connection = True
                self.send_header('Connection', 'close')
            self.end_headers(); self.wfile.write(payload)

        def authorized(self):
            return self.valid_host() and hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer '+token)

        def do_GET(self):
            if not self.valid_host(): return self.reply(403, {'error': 'Local app only'})
            if self.path in ASSETS:
                name, mime = ASSETS[self.path]
                return self.reply(200, (ROOT/'tavi/web'/name).read_bytes(), mime)
            if not self.authorized(): return self.reply(403, {'error': 'Open the Paprika Mac app'})
            if self.path == '/api/desktop/status':
                async def status():
                    from experiments.memory import native_voice
                    return {'service': 'paprika-core', 'protocol': PROTOCOL, 'instance': instance,
                            'reply_prompt_sha256': hashlib.sha256(native_voice.MISSION.encode()).hexdigest(),
                            'prerequisites': await asyncio.to_thread(readiness),
                            'spent_or_reserved_usd': store.used_micro_usd()/1e6, 'budget_usd': APPROVED_BUDGET_MICRO_USD/1e6,
                            'audio_endpoint': 'mac', 'cloud_audio': False, 'recording_retained': False,
                            **({'family':household.status()} if household else {})}
                try: return self.reply(200, asyncio.run_coroutine_threadsafe(status(), loop).result(5))
                except Exception: return self.reply(503, {'error': 'Local readiness check unavailable. Retry here.'})
            if self.path in ('/api/conversation/audio', '/api/conversation/diagnostics'):
                return super().do_GET()
            if calibration and self.path in ('/api/voices/status','/api/voices/state'):
                try:
                    if self.path=='/api/voices/status':return self.reply(200,calibration.status())
                    return self.reply(200,calibration.state(self.headers.get('X-Voice-Session'),self.headers.get('X-Voice-Person')))
                except (OSError,ValueError,KeyError):return self.reply(400,{'error':'Voice checks are unavailable. Connect the external drive and reopen this page.'})
            if calibration and self.path=='/api/voices/audio':
                try:return self.reply(200,calibration.audio(self.headers.get('X-Voice-Session'),self.headers.get('X-Voice-Person'),self.headers.get('X-Voice-Sample')),'audio/wav')
                except (ValueError,OSError):return self.reply(404,{'error':'No listening copy is available. Use your supervision to review.'})
            if calibration and self.path.startswith('/api/voices/question/'):
                pid=self.path.removeprefix('/api/voices/question/')
                try:
                    manifest=json.loads((ROOT/'experiments/speaker-id/family-prompt-audio-assets-v1.json').read_text())
                    entry=next(p for p in manifest['prompts'] if p['id']==pid)
                    from tavi.experiment_workflow import digest
                    file=Path(entry['path'])
                    if digest(file)!=entry['sha256']:raise ValueError('Question audio changed')
                    return self.reply(200,file.read_bytes(),'audio/wav')
                except (OSError,StopIteration,ValueError):return self.reply(404,{'error':'A grown-up can read this question; recording stays off.'})
            return self.reply(404, {'error': 'Unknown app action'})

        def do_POST(self):
            if not self.authorized(): return self.reply(403, {'error': 'Open the Paprika Mac app'})
            origin = self.headers.get('Origin')
            if origin and origin not in (f'http://127.0.0.1:{port}', f'http://localhost:{port}'):
                return self.reply(403, {'error': 'Untrusted app origin'})
            if calibration and self.path.startswith('/api/voices/'):
                try:
                    action=self.path.removeprefix('/api/voices/');size=int(self.headers.get('Content-Length','0'))
                    if not 0<size<=160000:raise ValueError('Invalid voice check size')
                    raw=self.rfile.read(size);person=self.headers.get('X-Voice-Person');session=self.headers.get('X-Voice-Session')
                    if action=='attempt':
                        if self.headers.get('Content-Type')!='application/octet-stream':raise ValueError('Expected local PCM')
                        settings=self.headers.get('X-Voice-Settings','{}')
                        if len(settings)>512:raise ValueError('Invalid microphone settings')
                        result=calibration.attempt(session,person,self.headers.get('X-Voice-Attempt'),self.headers.get('X-Voice-Prompt'),raw,capture_settings=json.loads(settings))
                    else:
                        if size>8192:raise ValueError('Invalid voice check command')
                        body=json.loads(raw)
                        if not isinstance(body,dict):raise ValueError('Expected local voice command')
                        if action=='begin':result=calibration.begin(body,session)
                        elif action=='review':result=calibration.review(session,person,body['choices'],body.get('attested'),finish_visit=body.get('finish') is True)
                        elif action=='skip':result=calibration.skip(session,person,body['id'],body['prompt'])
                        elif action=='fit':result=calibration.fit()
                        elif action=='qualify':result=calibration.qualify()
                        else:raise ValueError('Unknown voice check action')
                    return self.reply(200,result)
                except (ValueError,OSError,KeyError,TypeError):return self.reply(400,{'error':'This local voice check could not finish. Earlier examples are kept; keep the page open and retry or review saved progress.'})
            if self.path == '/api/desktop/pause':
                try:
                    asyncio.run_coroutine_threadsafe(base.stop_capture(), loop).result(5)
                    return self.reply(200, {'stopped': True})
                except Exception: return self.reply(503, {'error': 'Local endpoint cleanup pending'})
            if self.path == '/api/desktop/save-review':
                try:
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 < size <= 16384: raise ValueError('Feedback too large')
                    body = json.loads(self.rfile.read(size))
                    if (body.get('kind') != 'paprika_mac_adult_check' or body.get('real_audio_retained') is not False
                            or body.get('result') not in ('worked','problem','unsure')):
                        raise ValueError('Invalid feedback')
                    directory = ROOT/'.tavi/mac/reviews'; directory.mkdir(mode=0o700, parents=True, exist_ok=True)
                    if len(list(directory.glob('*.json'))) >= 100: raise ValueError('Local review storage is full; earlier results are kept')
                    file = directory/(uuid4().hex+'.json')
                    with os.fdopen(os.open(file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w') as out:
                        json.dump(body, out); out.flush(); os.fsync(out.fileno())
                    return self.reply(200, {'saved': True})
                except (ValueError, AttributeError, OSError):
                    return self.reply(400, {'error': 'Feedback could not be saved. Keep this page open and try again.'})
            command = self.path.removeprefix('/api/conversation/')
            if not self.path.startswith('/api/conversation/') or command not in POSTS:
                return self.reply(404, {'error': 'Unknown app action'})
            if command == 'start':
                # Read once, then use the same base parser through an in-memory stream.
                from io import BytesIO
                try:
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 < size <= 2048: raise ValueError('Choose the recording and processing options first')
                    raw = self.rfile.read(size); body = json.loads(raw)
                    if (body.get('consent') != CONSENT or body.get('adult') is not True
                            or body.get('local_audio_only') is not True or body.get('retain_audio') is not False
                            or body.get('endpoint_id') != 'mac' or body.get('protocol') != PROTOCOL
                            or type(body.get('online')) is not bool):
                        raise ValueError('Confirm adult supervision, local audio and your reply choice before starting')
                    if not readiness()['ready']: raise ValueError('Connect the external drive and check local files before starting')
                    if body['online'] and not readiness()['cloud_key']: raise ValueError('OpenAI key is unavailable. Choose offline or restore local configuration')
                    self.rfile = BytesIO(raw)
                except (ValueError, TypeError, AttributeError):
                    return self.reply(400, {'error': 'Complete setup and check the external drive. Nothing is recording.'})
            return super().do_POST()
    return Handler


async def serve(port=8785):
    os.chdir(ROOT)
    private = ROOT/'.tavi/mac'; private.mkdir(mode=0o700, parents=True, exist_ok=True); os.chmod(private, 0o700)
    lock = os.open(private/'core.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    token = os.environ.pop('PAPRIKA_CORE_TOKEN', '')
    if len(token) < 48: raise ValueError('Core must be started by its local owner')
    instance = uuid4().hex
    store = Store(ROOT/'.tavi/simulation/simulation.sqlite3', must_exist=True)  # SAME ledger, never reset.
    demo = Demo(store); loop = asyncio.get_running_loop()
    from tavi.household_runtime import HouseholdRuntime
    from tavi.voice_calibration import VoiceCalibration
    from tavi.calibration_service import bind_visit,seal_visit
    from tavi.speaker_process import SpeakerProcess
    household=HouseholdRuntime();calibration=VoiceCalibration(household.catalog,SpeakerProcess(),bind=bind_visit,seal=seal_visit)
    base = handler_for(demo, loop, port, wake_backend='off', voice_backend='kokoro-k-mlx',
                       final_asr='turbo-mlx', reply_delivery='sentences', conversation_factory=household.conversation,
                       session_host=household,identity_observer=household)
    server = LocalHTTPServer(('127.0.0.1', port), handler(base, loop, store, port, token, instance,household=household,calibration=calibration))
    server.daemon_threads = True
    record = private/'core.json'
    fd = os.open(record, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w') as out: json.dump({'pid': os.getpid(), 'port': port, 'token': token, 'instance': instance, 'protocol': PROTOCOL}, out)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM): loop.add_signal_handler(sig, stop.set)
    try: await stop.wait()
    finally:
        await base.close_conversation()
        await asyncio.to_thread(base.close_live)
        await asyncio.to_thread(calibration.encoder.close)
        await asyncio.to_thread(server.shutdown)
        server.server_close(); store.close()
        if record.exists() and json.loads(record.read_text()).get('instance') == instance: record.unlink()
        os.close(lock)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--port', type=int, default=8785); args = parser.parse_args()
    if not 1024 <= args.port <= 65535: parser.error('Invalid local port')
    asyncio.run(serve(args.port))


if __name__ == '__main__': main()
