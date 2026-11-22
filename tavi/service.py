"""Loopback simulator, audio experiments and explicitly started conversation."""
import argparse
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import signal
from socketserver import TCPServer
import threading
from urllib.parse import urlsplit

from .contracts import Event, Kind
from .runtime import Controller
from .storage import APPROVED_BUDGET_MICRO_USD, Store

BUDGET_MICRO_USD = APPROVED_BUDGET_MICRO_USD

class LocalHTTPServer(ThreadingHTTPServer):
    def service_actions(self):
        expire = getattr(self.RequestHandlerClass, "expire_audio", None)
        if expire:
            expire()

    def server_bind(self):
        # This loopback service needs no reverse-DNS lookup on startup.
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]

class Demo:
    def __init__(self, store: Store, *, pace: float = 1):
        self.pace = pace
        self.store = store
        self.controller = Controller(store)
        self.tasks: set[asyncio.Task] = set()

    def state(self):
        return {**self.controller.snapshot(), "paid_apis_enabled": False,
                "budget_usd": BUDGET_MICRO_USD / 1_000_000,
                "reserved_or_spent_usd": self.store.used_micro_usd() / 1_000_000,
                "pending_memory_jobs": len(self.store.pending())}

    async def command(self, command: str, body: dict) -> dict:
        c = self.controller
        new_task = None
        if command == "state":
            return self.state()
        if command == "say":
            text = body.get("text", "")
            speaker = body.get("speaker", "unknown")
            if not isinstance(text, str) or not text.strip() or len(text) > 2000:
                raise ValueError("Enter 1–2000 characters of fictional test speech")
            if speaker not in ("unknown", "adultone", "adulttwo", "childtwo", "childone"):
                raise ValueError("Invalid simulated identity")
            token = c.begin()
            new_task = asyncio.create_task(self._respond(token, text.strip(), speaker))
            self.tasks.add(new_task)
            new_task.add_done_callback(self.tasks.discard)
        elif command in ("interrupt", "mute", "unmute", "end", "offline", "online"):
            if command == "interrupt":
                c.cancel()
            elif command in ("mute", "unmute"):
                c.mute(command == "mute")
            elif command == "end":
                c.end()
            else:
                c.connected(command == "online")
        else:
            raise ValueError("Unknown command")
        # Tasks are cancelled too, but correctness does not depend on cooperative
        # cancellation: every callback is checked against its original token.
        for task in tuple(self.tasks):
            if command != "say" or task is not new_task:
                task.cancel()
        return self.state()

    async def _respond(self, token, text, speaker):
        try:
            await asyncio.sleep(1 * self.pace)
            if not self.controller.apply(Event.make(Kind.IDENTITY, token, speaker=speaker)):
                return
            await asyncio.sleep(1 * self.pace)
            if not self.controller.apply(Event.make(Kind.TRANSCRIPT, token, text=text)):
                return
            await asyncio.sleep(3 * self.pace)
            for sequence, chunk in enumerate(("I heard your test message.", "This response is simulated.")):
                if not self.controller.apply(Event.make(Kind.AUDIO, token, sequence=sequence, duration_ms=1800, text=chunk)):
                    return
                await asyncio.sleep(1.8 * self.pace)
                if not self.controller.apply(Event.make(Kind.PLAYED, token, sequence=sequence)):
                    return
            self.controller.apply(Event.make(Kind.DONE, token))
        except asyncio.CancelledError:
            pass

    async def close(self):
        for task in tuple(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.controller.end()


def handler_for(demo, loop, port, *, wake_backend="baseline", live_factory=None, voice_backend="mac",final_asr='tiny.en',reply_delivery='whole',memory_pilot=False,learning_pilot=False,conversation_factory=None,session_host=None,identity_observer=None):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    web = Path(__file__).with_name("web")
    page = (web / "index.html").read_bytes()
    acoustic = None
    audio_lock = threading.Lock()
    live = None
    live_lock = threading.Lock()
    from .conversation import Conversation
    if voice_backend not in ('mac', 'piper', 'kokoro-k', 'kokoro-k-mlx'):
        raise ValueError('Unknown voice backend')
    if final_asr not in ('tiny.en','base.en','turbo-mlx'):raise ValueError('Unknown final transcription model')
    from .local_speech import LocalSpeech
    if reply_delivery not in ('whole','sentences'): raise ValueError('Unknown reply delivery')
    if reply_delivery=='sentences':
        from .chunked_conversation import ChunkedConversation
        conversation_class = ChunkedConversation
    else:
        conversation_class = Conversation
    speech=LocalSpeech(voice_backend) if voice_backend != 'mac' else None
    schedule=None
    if final_asr=='turbo-mlx' and speech is not None:
        from .inference_schedule import ScheduledSpeech
        schedule=ScheduledSpeech(speech,loop)
        speech=schedule
    pilot = None
    if memory_pilot or learning_pilot:
        if reply_delivery!='sentences' or final_asr!='turbo-mlx':raise ValueError('Memory pilot requires the qualified local voice path')
        if learning_pilot:
            from experiments.memory.learning_pilot import LearningPilot
            pilot=LearningPilot(demo.store)
        else:
            from experiments.memory.adult_pilot import AdultMemoryPilot
            pilot=AdultMemoryPilot(demo.store)
    conversation = (conversation_factory(demo.store,speech=speech) if conversation_factory else
                    pilot.conversation(demo.store,speech=speech) if pilot else conversation_class(demo.store, speech=speech))
    conversation_start_lock = asyncio.Lock()
    capture_epoch = 0
    abandoned_starts = set()
    asr_selection={'partial':'tiny.en','final':final_asr,
                   'partial_prompt':'Names: Tavi, Paprika.',
                   'final_prompt':None if final_asr=='turbo-mlx' else 'Names: Tavi, Paprika.'}
    cached_conversation = {**conversation.snapshot(),'asr_models':asr_selection}
    frame_mailbox_lock = threading.Lock()
    pending_conversation_frames = 0

    def publish_conversation():
        nonlocal cached_conversation
        cached_conversation = {**conversation.snapshot(),'asr_models':asr_selection}
        if pilot:
            cached_conversation.update(memory_enabled=True,memory_policy='read-only fictional Nora role; not voice identification')
            if learning_pilot:
                cached_conversation.update(memory_policy='adult fictional Mira; automatic learning; not voice identification',**pilot.extra_state(conversation))
            pilot.persist(conversation)
        return cached_conversation

    def consume_conversation_frame(lease, result):
        nonlocal pending_conversation_frames
        try:
            if conversation.lease == lease:
                conversation.feed(lease, result)
                publish_conversation()
        finally:
            with frame_mailbox_lock:
                pending_conversation_frames -= 1

    async def conversation_command(command, body):
        nonlocal capture_epoch
        # Bind before waiting for another start: a pause cancels queued setup too.
        issued_epoch = capture_epoch
        lease = body.get('stream_id')
        if command == 'start':
            async with conversation_start_lock:
                def current():
                    if issued_epoch != capture_epoch:
                        raise ValueError('Listening setup was cancelled. Start again explicitly.')
                current()
                try:
                    if pilot:await pilot.prepare(body)
                    if session_host:await session_host.prepare(body)
                    current()
                    if hasattr(conversation.speech, 'prepare'):
                        await conversation.speech.prepare()
                    current()
                    if body['online'] and conversation.provider is None:
                        from .conversation_providers import PaidText
                        provider = await asyncio.to_thread(PaidText, demo.store)
                        conversation.provider = provider
                        import anyio
                        await anyio.sleep(0)  # Resolve the async transport backend before PCM starts.
                    current()
                    starting = asyncio.create_task(asyncio.to_thread(live_command, 'start', {'mode': 'hinted'}))
                    try:
                        started = await asyncio.shield(starting)
                    except asyncio.CancelledError:
                        # Cancelling to_thread cannot stop native initialization.
                        # Keep its eventual lease owned and retire only that lease.
                        async def retire_late_start():
                            late = await starting
                            await asyncio.to_thread(live_command, 'stop', {'stream_id': late['stream_id']})
                        cleanup = asyncio.create_task(retire_late_start())
                        abandoned_starts.add(cleanup)
                        def settled(task):
                            abandoned_starts.discard(task)
                            if not task.cancelled():task.exception() # Retrieve failures; never replay setup.
                        cleanup.add_done_callback(settled)
                        raise
                    if issued_epoch != capture_epoch:
                        await asyncio.to_thread(live_command, 'stop', {'stream_id': started['stream_id']})
                        current()
                    conversation.start(started['stream_id'], body['online'])
                    return {**started, 'conversation': publish_conversation()}
                except BaseException:
                    if learning_pilot and pilot.folder is not None:await pilot.end_learning()
                    raise
        if command == 'stop':
            if not lease:
                raise ValueError('A capture lease is required')
            conversation.stop(lease)
            if learning_pilot and pilot.stop_task is None:
                pilot.stop_task=asyncio.create_task(pilot.end_learning())
            publish_conversation()
            return await asyncio.to_thread(live_command, 'stop', {'stream_id': lease})
        if command == 'learning-checkpoint':
            if not learning_pilot or not lease or lease!=conversation.lease:raise ValueError('Learning conversation lease expired')
            result=await pilot.checkpoint(conversation,body.get('checkpoint'))
            return {**result,'conversation':publish_conversation()}
        if command == 'audio':
            if reply_delivery=='sentences':
                value = body.get('sequence')
                if not isinstance(value,str) or not value.isascii() or not value.isdigit() or len(value)>3:
                    raise ValueError('Expected a chunk sequence')
                return conversation.audio_bytes(lease,body['response_id'],int(value))
            return conversation.audio_bytes(lease, body['response_id'])
        if command == 'diagnostics':
            return {**conversation.snapshot(diagnostics=True),'asr_models':asr_selection,
                    **(pilot.extra_state(conversation) if learning_pilot else {}),
                    'inference_schedule':dict(schedule.metrics) if schedule else None}
        if command == 'online' and body.get('enabled') is True and conversation.provider is None:
            if lease != conversation.lease or not lease:
                raise ValueError('Conversation lease expired')
            async with conversation_start_lock:
                if conversation.provider is None:
                    from .conversation_providers import PaidText
                    conversation.provider = await asyncio.to_thread(PaidText, demo.store)
                    import anyio
                    await anyio.sleep(0)
        accepted = conversation.command(lease, command, body)
        return {'accepted': accepted, 'conversation': publish_conversation()}

    def live_command(command, body):
        nonlocal live
        with live_lock:
            if live is None:
                if command != 'start':
                    raise ValueError('Start the live microphone first')
                if live_factory:
                    live = live_factory()
                else:
                    from .acoustics import Silero
                    from .live_wake import LiveWake, WhisperDecoder
                    decoder = WhisperDecoder(final_model=final_asr,schedule=schedule)
                    live = LiveWake(Silero(Path('.tavi/models/silero_vad.onnx'), wake_backend='off'), decoder,identity_observer=identity_observer)
            if command == 'start':
                return live.start(body['mode'])
            if command == 'stop':
                return live.stop(body['stream_id'])
            return live.feed(body['stream_id'], body['sequence'], body['pcm'])

    def audio_command(command, body):
        nonlocal acoustic
        from .acoustics import AcousticSession, Silero
        with audio_lock:
            if acoustic is None:
                acoustic = AcousticSession(Silero(Path(".tavi/models/silero_vad.onnx"), wake_backend=wake_backend))
            if command == "start":
                return acoustic.start()
            if command == "stop":
                if body["stream_id"] == acoustic.stream_id:
                    acoustic.stop()
                return {"stopped": True}
            return acoustic.feed(body["stream_id"], body["sequence"], body["pcm"])

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        @staticmethod
        def expire_audio():
            loop.call_soon_threadsafe(conversation.expire)
            if audio_lock.acquire(blocking=False):
                try:
                    if acoustic:
                        acoustic.expire()
                finally:
                    audio_lock.release()
            if live_lock.acquire(blocking=False):
                try:
                    if live:
                        live.expire()
                finally:
                    live_lock.release()

        @staticmethod
        def close_live():
            if live:
                live.close()

        @staticmethod
        async def close_conversation():
            if abandoned_starts:
                await asyncio.gather(*abandoned_starts, return_exceptions=True)
                abandoned_starts.clear()
            await conversation.close()
            if pilot:await pilot.close(conversation)
            if session_host:await session_host.close()

        @staticmethod
        async def stop_capture():
            """Explicit endpoint loss/suspend; service lifetime is independent."""
            nonlocal capture_epoch
            capture_epoch += 1
            lease = conversation.lease
            conversation.stop()
            publish_conversation()
            if lease:
                await asyncio.to_thread(live_command, 'stop', {'stream_id': lease})

        def log_message(self, *_):
            pass  # Do not log fictional transcripts or query strings.

        def reply(self, status, data, content_type="application/json"):
            payload = data if isinstance(data, bytes) else json.dumps(data).encode()
            self.send_response(status)
            if status >= 400:
                self.close_connection = True
                self.send_header("Connection", "close")
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; media-src 'self' blob:; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(payload)

        def valid_host(self):
            return self.headers.get("Host") in allowed_hosts

        def invoke(self, command, body):
            future = asyncio.run_coroutine_threadsafe(demo.command(command, body), loop)
            try:
                self.reply(200, future.result(timeout=3))
            except ValueError as exc:
                self.reply(400, {"error": str(exc)})
            except TimeoutError:
                future.cancel()
                self.reply(503, {"error": "Controller unavailable"})

        def audio_invoke(self, command, body):
            future = asyncio.run_coroutine_threadsafe(asyncio.to_thread(audio_command, command, body), loop)
            try:
                self.reply(200, future.result(timeout=10 if command == "start" else 2))
            except (ValueError, FileNotFoundError, ImportError) as exc:
                self.reply(400, {"error": str(exc) + "; see audio setup instructions"})
            except TimeoutError:
                future.cancel()
                self.reply(503, {"error": "Local audio processing timeout"})

        def live_invoke(self, command, body):
            future = asyncio.run_coroutine_threadsafe(asyncio.to_thread(live_command, command, body), loop)
            try:
                self.reply(200, future.result(timeout=20 if command == 'start' else 2))
            except (ValueError, FileNotFoundError, ImportError) as exc:
                self.reply(400, {'error': str(exc)})
            except TimeoutError:
                future.cancel()
                self.reply(503, {'error': 'Local recognition service unavailable'})

        def conversation_invoke(self, command, body):
            nonlocal pending_conversation_frames
            if command == 'frame':
                # VAD/ASR submission and frame ACKs are independent of cloud
                # setup, response parsing, SQLite settlement and TTS callbacks.
                # No PCM is queued onto the controller loop, only bounded events.
                try:
                    result = live_command('frame', body)
                    with frame_mailbox_lock:
                        if pending_conversation_frames >= 16:
                            live_command('stop', {'stream_id': body['stream_id']})
                            loop.call_soon_threadsafe(conversation.stop, body['stream_id'])
                            raise ValueError('Conversation controller backlog; capture stopped')
                        pending_conversation_frames += 1
                    loop.call_soon_threadsafe(consume_conversation_frame, body['stream_id'], result)
                    return self.reply(200, {**result, 'conversation': cached_conversation})
                except (ValueError, FileNotFoundError, ImportError) as exc:
                    return self.reply(400, {'error': str(exc)})
            future = asyncio.run_coroutine_threadsafe(conversation_command(command, body), loop)
            try:
                result = future.result(timeout=60 if learning_pilot and command=='start' else 20 if command in ('start','learning-checkpoint') else 2)
                self.reply(200, result, 'audio/wav' if command == 'audio' else 'application/json')
            except (ValueError, FileNotFoundError, ImportError) as exc:
                self.reply(400, {'error': str(exc)})
            except TimeoutError:
                future.cancel()
                self.reply(503, {'error': 'Conversation service unavailable'})

        def do_GET(self):
            if not self.valid_host():
                return self.reply(403, {"error": "Localhost only"})
            if self.path == "/":
                return self.reply(200, page, "text/html; charset=utf-8")
            if self.path == '/api/conversation/audio':
                return self.conversation_invoke('audio', {'stream_id': self.headers.get('X-Audio-Stream'),
                                                        'response_id': self.headers.get('X-Response-Id'),
                                                        'sequence': self.headers.get('X-Audio-Sequence')})
            if self.path == '/api/conversation/diagnostics':
                return self.conversation_invoke('diagnostics', {})
            voice_samples = {f'/voice-check/sample-{n}.wav': Path(f'.tavi/voice-check/sample-{n}.wav') for n in range(1,5)}
            voice_samples.update({f'/voice-audition/sample-{n}.wav': Path(f'.tavi/voice-audition/sample-{n}.wav') for n in range(1,9)})
            voice_samples.update({f'/voice-texture/sample-{n}.wav': Path(f'.tavi/voice-texture/sample-{n}.wav') for n in range(1,7)})
            voice_samples.update({f'/voice-texture-range/sample-{n}.wav': Path(f'.tavi/voice-texture-range/sample-{n}.wav') for n in range(1,11)})
            voice_samples.update({f'/voice-direction/sample-{n}.wav': Path(f'.tavi/voice-direction/sample-{n}.wav') for n in range(1,9)})
            voice_samples.update({f'/voice-husky/sample-{n}.wav': Path(f'.tavi/voice-husky/sample-{n}.wav') for n in range(1,9)})
            if self.path in voice_samples:
                path = voice_samples[self.path]
                if not path.is_file():
                    return self.reply(404, {'error': 'Local listening sample not prepared'})
                return self.reply(200, path.read_bytes(), 'audio/wav')
            assets = {"/audio": (web / "audio.html", "text/html; charset=utf-8"),
                      "/voice-check": (web / "voice-check.html", "text/html; charset=utf-8"),
                      "/voice-check.js": (web / "voice-check.js", "text/javascript"),
                      "/voice-check-protocol.json": (web / "voice-check-protocol.json", "application/json"),
                      "/voice-audition-protocol.json": (web / "voice-audition-protocol.json", "application/json"),
                      "/voice-texture-protocol.json": (web / "voice-texture-protocol.json", "application/json"),
                      "/voice-texture-range-protocol.json": (web / "voice-texture-range-protocol.json", "application/json"),
                      "/voice-direction-protocol.json": (web / "voice-direction-protocol.json", "application/json"),
                      "/voice-husky-protocol.json": (web / "voice-husky-protocol.json", "application/json"),
                      "/live-wake": (web / "live-wake.html", "text/html; charset=utf-8"),
                      "/live-wake.js": (web / "live-wake.js", "text/javascript"),
                      "/conversation": (web / ("learning-conversation.html" if learning_pilot else "memory-conversation.html" if pilot else "conversation.html"), "text/html; charset=utf-8"),
                      "/conversation.js": (web / "conversation.js", "text/javascript"),
                      "/chunk-audio-prefetch.js": (web / "chunk-audio-prefetch.js", "text/javascript"),
                      "/conversation_guide.js": (web / "conversation_guide.js", "text/javascript"),
                      "/memory-conversation-guide.js": (web / "memory-conversation-guide.js", "text/javascript"),
                      "/learning-conversation-guide.js": (web / "learning-conversation-guide.js", "text/javascript"),
                      "/local-audio-recording.js": (web / "local-audio-recording.js", "text/javascript"),
                      "/speech-check": (web / "speech-check.html", "text/html; charset=utf-8"),
                      "/speech-check.js": (web / "speech-check.js", "text/javascript"),
                      "/speech-check-session.js": (web / "speech-check-session.js", "text/javascript"),
                      "/speech-check-protocol.json": (web / "speech-check-protocol.json", "application/json"),
                      "/mic-check": (web / "mic-check.html", "text/html; charset=utf-8"),
                      "/mic-check.js": (web / "mic-check.js", "text/javascript"),
                      "/paprika-reference.wav": (Path(".tavi/audio/paprika-reference.wav"), "audio/wav"),
                      "/wake-samples": (web / "wake-samples.html", "text/html; charset=utf-8"),
                      "/name-comparison": (web / "name-comparison.html", "text/html; charset=utf-8"),
                      "/name-comparison-protocol.json": (web / "name-comparison-protocol.json", "application/json"),
                      "/wake-samples.js": (web / "wake-samples.js", "text/javascript"),
                      "/sample-collector.js": (web / "sample-collector.js", "text/javascript"),
                      "/audio.js": (web / "audio.js", "text/javascript"),
                      "/capture.js": (web / "capture.js", "text/javascript"),
                      "/interruption.js": (web / "interruption.js", "text/javascript"),
                      "/guided-wake.js": (web / "guided-wake.js", "text/javascript"),
                      "/reference.wav": (Path(".tavi/audio/reference.wav"), "audio/wav")}
            # Fresh-test links may carry a harmless query without touching the
            # unsaved recording in an already-open conversation page.
            asset_path=urlsplit(self.path).path
            if asset_path in assets:
                path, mime = assets[asset_path]
                if not path.exists():
                    return self.reply(404, {"error": "Run python -m tavi.setup_audio first"})
                content=path.read_bytes()
                if asset_path=='/conversation' and reply_delivery=='sentences':
                    content=content.replace(b'data-guide="k-live"',b'data-guide="k-live" data-delivery="sentences"')
                if asset_path=='/conversation' and final_asr=='turbo-mlx':
                    content=content.replace(b'data-guide="k-live"',b'data-guide="k-live" data-final-asr="turbo-mlx"')
                return self.reply(200, content, mime)
            if self.path == "/api/state":
                return self.invoke("state", {})
            self.reply(404, {"error": "Not found"})

        def do_POST(self):
            origin = self.headers.get("Origin")
            if not self.valid_host() or (origin and origin not in {"http://" + host for host in allowed_hosts}):
                return self.reply(403, {"error": "Local origin required"})
            if self.path=='/api/conversation/save-test':
                try:
                    from .saved_tests import save_test, MAX_BYTES
                    if cached_conversation['lease_active']:raise ValueError('Mute the microphone before saving')
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<size<=MAX_BYTES or self.headers.get('Content-Type')!='application/json':
                        raise ValueError('Invalid test-result request')
                    return self.reply(200,save_test(self.rfile.read(size)))
                except (ValueError,UnicodeDecodeError,OSError) as error:
                    return self.reply(400,{'error':str(error)})
            if self.path.startswith('/api/conversation/'):
                try:
                    command = self.path.rsplit('/', 1)[-1]
                    if command not in ('start','stop','frame','started','played','interrupt','end','online','learning-checkpoint'):
                        raise ValueError('Unknown conversation action')
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 <= size <= 2048:
                        raise ValueError('Conversation request is too large')
                    raw = self.rfile.read(size)
                    lease = self.headers.get('X-Audio-Stream')
                    if command == 'frame':
                        if size != 1024 or self.headers.get('Content-Type') != 'application/octet-stream':
                            raise ValueError('Expected 512 PCM16 samples')
                        body = {'sequence': int(self.headers.get('X-Audio-Sequence','-1')), 'pcm': raw, 'stream_id': lease}
                    else:
                        body = json.loads(raw) if raw else {}
                        if not isinstance(body, dict):
                            raise ValueError('Expected a small conversation command')
                        body['stream_id'] = lease
                        if command == 'start' and type(body.get('online')) is not bool:
                            raise ValueError('Choose online replies on or off')
                    return self.conversation_invoke(command, body)
                except (ValueError, UnicodeDecodeError) as exc:
                    return self.reply(400, {'error': str(exc)})
            if self.path in ('/api/live-wake/start', '/api/live-wake/stop', '/api/live-wake/frame'):
                try:
                    command = self.path.rsplit('/', 1)[-1]
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 <= size <= 1024:
                        raise ValueError('Invalid live-audio request size')
                    data = self.rfile.read(size)
                    if command == 'frame':
                        if size != 1024 or self.headers.get('Content-Type') != 'application/octet-stream':
                            raise ValueError('Expected 512 PCM16 samples')
                        body = {'stream_id': self.headers.get('X-Audio-Stream'),
                                'sequence': int(self.headers.get('X-Audio-Sequence', '-1')), 'pcm': data}
                    elif command == 'start':
                        if self.headers.get('Content-Type') != 'application/json':
                            raise ValueError('Expected a mode selection')
                        body = json.loads(data)
                        if not isinstance(body, dict) or body.get('mode') not in ('hinted', 'unhinted'):
                            raise ValueError('Choose hinted or unhinted mode')
                    else:
                        body = {'stream_id': self.headers.get('X-Audio-Stream')}
                    return self.live_invoke(command, body)
                except (ValueError, UnicodeDecodeError) as exc:
                    return self.reply(400, {'error': str(exc)})
            if self.path in ("/api/audio/start", "/api/audio/stop", "/api/audio/frame"):
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 <= size <= 1024:
                        raise ValueError("Invalid audio size")
                    data = self.rfile.read(size)
                    if self.path.endswith("/frame"):
                        if self.headers.get("Content-Type") != "application/octet-stream" or size != 1024:
                            raise ValueError("Expected 512 PCM16 samples")
                        return self.audio_invoke("frame", {"stream_id": self.headers.get("X-Audio-Stream"),
                            "sequence": int(self.headers.get("X-Audio-Sequence", "-1")), "pcm": data})
                    return self.audio_invoke(self.path.rsplit("/", 1)[-1], {"stream_id": self.headers.get("X-Audio-Stream")})
                except ValueError as exc:
                    return self.reply(400, {"error": str(exc)})
            if self.path != "/api/command":
                return self.reply(404, {"error": "Not found"})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 8192 or self.headers.get("Content-Type") != "application/json":
                    raise ValueError()
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict) or not isinstance(body.get("command"), str):
                    raise ValueError()
            except (ValueError, UnicodeDecodeError):
                return self.reply(400, {"error": "Expected a small JSON command"})
            self.invoke(body["command"], body)
    return Handler

async def serve(port: int, data_dir: Path, wake_backend: str = "baseline", voice_backend: str = "mac",final_asr='tiny.en',reply_delivery='whole',memory_pilot=False,learning_pilot=False):
    data_dir.mkdir(parents=True, exist_ok=True)
    store = Store(data_dir / "simulation.sqlite3")
    demo = Demo(store)
    server = LocalHTTPServer(("127.0.0.1", port), handler_for(demo, asyncio.get_running_loop(), port, wake_backend=wake_backend, voice_backend=voice_backend,final_asr=final_asr,reply_delivery=reply_delivery,memory_pilot=memory_pilot,learning_pilot=learning_pilot))
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Tavi offline simulator: http://127.0.0.1:{port}", flush=True)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        await stop.wait()
    finally:
        await demo.close()
        await server.RequestHandlerClass.close_conversation()
        await asyncio.to_thread(server.RequestHandlerClass.close_live)
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        store.close()

def main():
    parser = argparse.ArgumentParser(description="Local audio labs and controlled conversation (browser Start required; cloud text only after engagement)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path, default=Path(".tavi/simulation"))
    parser.add_argument("--wake-backend", choices=("baseline", "hey", "custom", "off"), default="baseline")
    parser.add_argument("--voice-backend", choices=("mac", "piper", "kokoro-k", "kokoro-k-mlx"), default="kokoro-k-mlx")
    parser.add_argument('--final-asr',choices=('tiny.en','base.en','turbo-mlx'),default='base.en',help='Final request transcription; partial name detection stays tiny.en; turbo-mlx is unhinted and isolated')
    parser.add_argument('--reply-delivery',choices=('whole','sentences'),default='whole',help='Experimental completion-guarded sentence delivery')
    parser.add_argument('--memory-pilot',action='store_true',help='Opt-in adult fictional memory pilot; explicit browser consent required')
    parser.add_argument('--learning-pilot',action='store_true',help='Opt-in guided fictional automatic learning; explicit adult consent required')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    if args.memory_pilot and args.learning_pilot:parser.error('Choose one memory pilot')
    asyncio.run(serve(args.port, args.data_dir, args.wake_backend, args.voice_backend,args.final_asr,args.reply_delivery,memory_pilot=args.memory_pilot,learning_pilot=args.learning_pilot))
