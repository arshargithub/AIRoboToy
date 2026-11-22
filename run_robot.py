"""
Simplified robot pipeline using OpenAI Realtime API.
Uses local VAD as a cost gate, then activates Realtime API for seamless voice conversations.
Integrates speaker voice identification and Hindsight memory.
"""
import os
import time
import threading
import numpy as np
from robo_core.audio.microphone_stream import MicrophoneStream
from robo_core.vad.vad_engine import VADEngine
from robo_core.realtime.realtime_client import RealtimeAPIClient
from robo_core.audio.playback import AudioPlayer
from robo_core.utils.logger import get_logger
from robo_core.utils.config_loader import load_config, get_api_key
from robo_core.ui.robot_state import RobotState, RobotStateManager
from robo_core.ui.web_ui_server import WebUIServer
from robo_core.identity import SpeakerEncoder, SpeakerStore, SpeakerIdentifier
from robo_core.memory import HindsightClient

logger = get_logger(__name__)


def check_internet_connectivity(host="8.8.8.8", port=53, timeout=3):
    """Check if internet connectivity is available."""
    try:
        import socket
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except (socket.error, OSError):
        return False


class RealtimePipeline:
    """Manages the Realtime API pipeline with local VAD gate."""
    
    def __init__(self, config, state_manager, web_ui_server=None):
        """
        Initialize pipeline.
        
        Args:
            config: Configuration dictionary
            state_manager: RobotStateManager instance
            web_ui_server: WebUIServer instance (optional)
        """
        self.config = config
        self.state_manager = state_manager
        self.web_ui_server = web_ui_server
        self.ui_enabled = web_ui_server is not None
        
        # Audio components
        audio_config = config.get("audio", {})
        self.mic = MicrophoneStream(
            rate=audio_config.get("sample_rate", 16000),
            chunk=audio_config.get("chunk_size", 512)
        )
        
        # Local VAD for cost gate
        vad_config = config.get("vad", {})
        self.vad = VADEngine(speech_threshold=vad_config.get("speech_threshold", 0.5))
        
        # Realtime API client
        api_key = get_api_key("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OpenAI API key required. Set OPENAI_API_KEY in .env file.")
        
        realtime_config = config.get("realtime", {})
        self.realtime_client = RealtimeAPIClient(
            api_key=api_key,
            voice=realtime_config.get("voice", "alloy"),
            model=realtime_config.get("model", "gpt-4o-realtime-preview-2024-12-17")
        )
        
        # Audio player for responses
        self.player = AudioPlayer()
        
        # State tracking
        self.realtime_session_active = False
        self.last_interaction_time = None
        self.session_timeout = config.get("conversation", {}).get("session_timeout_seconds", 60)
        
        # Audio buffering for response
        self.response_audio_buffer = []
        self.response_audio_lock = threading.Lock()
        self.response_thread = None
        self.playing_response = False
        self._stop_playback = threading.Event()
        self._response_done = threading.Event()
        self._playback_generation = 0

        # --- Voice identity ---
        identity_config = config.get("identity", {})
        self.identity_enabled = identity_config.get("enabled", False)
        self.speaker_identifier = None
        if self.identity_enabled:
            encoder = SpeakerEncoder(
                model_source=identity_config.get(
                    "model", "speechbrain/spkrec-ecapa-voxceleb"
                ),
            )
            store = SpeakerStore(
                db_path=os.path.expanduser(
                    identity_config.get("voiceprint_db", "~/.johnny/voiceprints.db")
                ),
            )
            self.speaker_identifier = SpeakerIdentifier(
                encoder=encoder,
                store=store,
                sample_rate=audio_config.get("sample_rate", 16000),
                min_audio_seconds=identity_config.get("min_audio_seconds", 2.0),
                similarity_threshold=identity_config.get("similarity_threshold", 0.75),
            )
            logger.info(
                "Voice identity enabled (%d enrolled speakers)",
                store.count,
            )

        # --- Hindsight memory ---
        memory_config = config.get("memory", {})
        self.memory_enabled = memory_config.get("enabled", False)
        self.hindsight = None
        if self.memory_enabled:
            api_url = (
                os.environ.get("HINDSIGHT_API_URL")
                or memory_config.get("hindsight_api_url", "")
            )
            if api_url:
                self.hindsight = HindsightClient(
                    base_url=api_url,
                    bank_id=memory_config.get("bank_id", "johnny-robot"),
                )
                self.recall_limit = memory_config.get("recall_limit", 10)
                self.retain_context = memory_config.get(
                    "retain_context", "robot conversation"
                )
                logger.info("Hindsight memory enabled (url=%s)", api_url)
            else:
                logger.warning(
                    "Memory enabled but no HINDSIGHT_API_URL configured -- disabling"
                )
                self.memory_enabled = False

        # Per-turn tracking for identity + memory
        self._current_speaker: str | None = None
        self._last_user_transcript: str | None = None
        self._last_robot_transcript: str | None = None
        
        # Setup event handlers
        self._setup_event_handlers()

    def _set_state(self, new_state: RobotState):
        """Set backend state and emit to UI atomically."""
        self.state_manager.set_state(new_state)
        if self.ui_enabled:
            self.web_ui_server.emit_state_update(new_state)
    
    # ------------------------------------------------------------------
    # Identity + Memory helpers (run in background threads)
    # ------------------------------------------------------------------

    def _enrich_session(self) -> None:
        """Resolve speaker identity + recall memories, then update the session prompt.

        Called from a background thread right after input_audio_buffer.committed.
        """
        speaker_name = None
        memories_text = None

        # 1) Resolve speaker
        if self.speaker_identifier:
            result = self.speaker_identifier.result
            if result and result.is_known:
                speaker_name = result.name
                self._current_speaker = speaker_name
                logger.info("Enriching session for speaker: %s", speaker_name)
            else:
                self._current_speaker = None

        # 2) Recall memories for this speaker
        if self.memory_enabled and self.hindsight and speaker_name:
            try:
                tag = f"user:{speaker_name}"
                memories = self.hindsight.recall(
                    query=f"What do I know about {speaker_name}?",
                    tags=[tag],
                    limit=self.recall_limit,
                )
                if memories:
                    lines = []
                    for mem in memories:
                        fact = mem.get("fact") or mem.get("content") or mem.get("text", "")
                        if fact:
                            lines.append(f"- {fact}")
                    if lines:
                        memories_text = "\n".join(lines)
                        logger.info("Recalled %d memories for %s", len(lines), speaker_name)
            except Exception:
                logger.exception("Memory recall failed")

        # 3) Update session prompt if we have anything to inject
        if speaker_name or memories_text:
            self.realtime_client.update_session(
                speaker_name=speaker_name,
                memories=memories_text,
            )

    def _retain_turn(self) -> None:
        """Retain the completed conversation turn to Hindsight."""
        if not self.memory_enabled or not self.hindsight:
            return

        user_text = self._last_user_transcript
        robot_text = self._last_robot_transcript
        if not user_text and not robot_text:
            return

        speaker = self._current_speaker or "unknown"
        parts = []
        if user_text:
            parts.append(f"{speaker.title()}: {user_text}")
        if robot_text:
            parts.append(f"Johnny: {robot_text}")
        content = "\n".join(parts)

        tags = [f"user:{speaker}"]
        try:
            self.hindsight.retain(
                content=content,
                context=self.retain_context,
                tags=tags,
            )
        except Exception:
            logger.exception("Memory retain failed")

    def _setup_event_handlers(self):
        """Setup Realtime API event handlers for state transitions."""
        
        def on_speech_started(event):
            """Local VAD detected speech - transition to LISTENING."""
            logger.info(f"EVENT: input_audio_buffer.speech_started - {event}")
            
            # CRITICAL: Ignore speech detection while robot is speaking OR thinking.
            # While THINKING, new speech_started events can cause UI/state churn
            # (LISTENING <-> THINKING) before the current response resolves.
            current_state = self.state_manager.get_state()
            if current_state in (RobotState.TALKING, RobotState.THINKING):
                logger.debug(
                    "Ignoring speech_started event - robot is currently %s",
                    current_state.value
                )
                return
            if current_state == RobotState.LISTENING:
                # Realtime can emit speech_started repeatedly within same turn.
                # Re-emitting LISTENING floods UI queue and causes visual lag drift.
                logger.debug("Ignoring speech_started event - already LISTENING")
                return
            
            if not self.realtime_session_active:
                # Activate Realtime API session
                try:
                    logger.info("Connecting to Realtime API...")
                    self.realtime_client.connect()
                    self.realtime_session_active = True
                    self.last_interaction_time = time.time()
                    logger.info("✓ Realtime API session activated and connected")
                except Exception as e:
                    logger.error(f"✗ Failed to activate Realtime API session: {e}", exc_info=True)
                    return
            
            logger.info("STATE: READY → LISTENING")
            self._set_state(RobotState.LISTENING)

            # Reset identity buffer for new turn
            if self.speaker_identifier:
                self.speaker_identifier.reset()
            self._last_user_transcript = None
            self._last_robot_transcript = None
        
        def on_input_committed(event):
            """Input audio committed - transition to THINKING."""
            logger.info(f"EVENT: input_audio_buffer.committed - {event}")
            if self.realtime_session_active:
                self._response_done.clear()
                logger.info("STATE: LISTENING → THINKING")
                self._set_state(RobotState.THINKING)
                
                item_id = event.get("item_id")
                if item_id:
                    logger.info(f"Input committed for item {item_id}, waiting for response...")

                # Inject speaker identity + recalled memories into the session.
                # Runs in a background thread to avoid blocking the event loop.
                threading.Thread(
                    target=self._enrich_session, daemon=True
                ).start()
        
        def on_response_created(event):
            """Response created - log it."""
            logger.info(f"EVENT: response.created - {event}")
        
        def on_response_output_item_added(event):
            """Response output item added - might contain audio."""
            logger.info(f"EVENT: response.output_item.added - {event}")
            item = event.get("item", {})
            if item.get("type") == "message":
                content = item.get("content", [])
                for content_item in content:
                    if content_item.get("type") == "output_audio":
                        logger.info(f"Output audio item detected in response.output_item.added")
        
        def on_response_audio_delta(event):
            """Response audio chunk received - transition to TALKING and play audio."""
            audio_payload = event.get("delta") or event.get("audio")
            if isinstance(audio_payload, str):
                audio_size = len(audio_payload)
            elif isinstance(audio_payload, (bytes, bytearray)):
                audio_size = len(audio_payload)
            else:
                audio_size = 0
            logger.debug(f"EVENT: response.audio.delta - received {audio_size} bytes of audio")

            # Ignore empty audio events to avoid starting playback threads with no data.
            if audio_size <= 0:
                return
            
            # IMMEDIATE TRANSITION: Switch to TALKING as soon as we get ANY audio data
            if not self.playing_response and audio_size > 0:
                logger.info("STATE: THINKING → TALKING (audio response started)")
                self._set_state(RobotState.TALKING)
            
            # The audio chunk is already queued by _handle_event before this handler runs
            if not self.playing_response:
                # Stop any previous playback
                self.player.stop()
                
                # Stop any existing playback thread and clear its audio
                if self.response_thread is not None and self.response_thread.is_alive():
                    logger.warning("Stopping previous playback thread")
                    self._stop_playback.set()  # Signal thread to stop
                    self.playing_response = False
                    self.player.stop()  # Stop audio playback immediately
                    self.response_thread.join(timeout=1.0)  # Wait for it to stop
                    # Clear old audio from previous response
                    cleared = 0
                    while True:
                        audio = self.realtime_client.get_response_audio()
                        if audio is None:
                            break
                        cleared += 1
                    if cleared > 0:
                        logger.info(f"Cleared {cleared} old audio chunks from previous response")
                
                # ALWAYS clear stop_playback before starting a new thread
                # (it might be set from a previous cancelled response)
                self._stop_playback.clear()
                
                # Start playing response (the current chunk is already in the queue)
                self.playing_response = True
                
                # Start new response playback thread
                logger.info("Starting audio playback thread...")
                self._playback_generation += 1
                generation = self._playback_generation
                self.response_thread = threading.Thread(
                    target=self._play_response_audio,
                    args=(generation,),
                    daemon=True
                )
                self.response_thread.start()
        
        def on_response_done(event):
            """Response complete - transition back to LISTENING."""
            self._response_done.set()
            response = event.get("response", {})
            status = response.get("status", "")
            queue_size = self.realtime_client.get_queue_size()
            has_active_playback_thread = self.response_thread is not None and self.response_thread.is_alive()
            logger.info(f"EVENT: response.done - status: {status}, audio queue size: {queue_size}")
            
            # If response was cancelled, stop playback immediately
            # BUT don't clear the queue - the audio might still be valid for the next response
            if status == "cancelled":
                logger.info("Response was cancelled - stopping playback")
                self._stop_playback.set()  # Signal playback thread to stop
                self.player.stop()
                self.playing_response = False
                # Don't clear queue - cancelled responses might have valid audio that should play
                # The next response will handle clearing if needed
                # If cancellation happened before any audio/playback thread started,
                # transition immediately so we don't get stuck in THINKING.
                if queue_size == 0 and not has_active_playback_thread and self.realtime_session_active:
                    logger.info("Cancelled response with no playback thread - returning to LISTENING")
                    self._set_state(RobotState.LISTENING)
            elif status == "failed":
                # Failed responses may produce no audio delta, which means playback thread
                # never starts. In that case we must transition out of THINKING immediately.
                logger.warning("Response failed - returning to LISTENING")
                self._stop_playback.set()
                self.player.stop()
                self.playing_response = False
                if self.realtime_session_active:
                    self._set_state(RobotState.LISTENING)
            else:
                # For completed responses, DON'T set playing_response = False immediately
                # Let the playback thread drain the queue first
                # It will exit when queue is empty and it's waited long enough
                logger.info(f"Response completed - keeping playback active to drain {queue_size} queued chunks")
                # If no playback is active and queue is empty, there is nothing to drain.
                # Transition now to avoid lingering in THINKING.
                if queue_size == 0 and not self.playing_response and self.realtime_session_active:
                    logger.info("Response completed with no audio - returning to LISTENING")
                    self._set_state(RobotState.LISTENING)
            
            # Only set playing_response = False if cancelled, otherwise let thread drain queue
            if status in ("cancelled", "failed"):
                self.playing_response = False
            
            self.last_interaction_time = time.time()
            
            # Extract robot transcript from response output
            if status == "completed":
                for item in response.get("output", []):
                    if item.get("type") == "message":
                        for part in item.get("content", []):
                            transcript = part.get("transcript")
                            if transcript:
                                self._last_robot_transcript = transcript
                                logger.info(
                                    "Robot transcript: %s",
                                    transcript[:120],
                                )

                # Retain conversation turn to Hindsight (background)
                threading.Thread(
                    target=self._retain_turn, daemon=True
                ).start()

            if status == "cancelled" and has_active_playback_thread:
                logger.info("Response cancelled - audio thread will handle state transition")
            elif status == "cancelled":
                logger.info("Response cancelled - no active playback thread, transitioned immediately")
            else:
                logger.info(f"Response completed - audio thread will transition back when playback finishes")
        
        def on_input_transcription(event):
            """User speech transcript received."""
            transcript = event.get("transcript", "")
            if transcript:
                self._last_user_transcript = transcript
                logger.info("User transcript: %s", transcript[:120])

        def on_conversation_end(event):
            """Conversation ended - close session and return to READY."""
            self._close_session()
        
        # Register handlers
        self.realtime_client.on_event("input_audio_buffer.speech_started", on_speech_started)
        self.realtime_client.on_event("input_audio_buffer.committed", on_input_committed)
        self.realtime_client.on_event("response.created", on_response_created)
        self.realtime_client.on_event("response.output_item.added", on_response_output_item_added)
        self.realtime_client.on_event("response.audio.delta", on_response_audio_delta)
        self.realtime_client.on_event("response.output_audio.delta", on_response_audio_delta)
        self.realtime_client.on_event("response.done", on_response_done)
        self.realtime_client.on_event(
            "conversation.item.input_audio_transcription.completed",
            on_input_transcription,
        )
        self.realtime_client.on_event("conversation.item.completed", on_conversation_end)
    
    def _play_response_audio(self, generation):
        """Play response audio chunks as they arrive using a continuous stream."""
        logger.info("Audio playback thread started (generation=%s)", generation)
        total_bytes = 0
        chunks_received = 0
        empty_count = 0
        # Before response.done: tolerate long silence (streaming may have network gaps).
        # After response.done + queue empty: short grace then exit.
        MAX_EMPTY_BEFORE_DONE = 600   # ~3s at 5ms sleep
        MAX_EMPTY_AFTER_DONE = 40     # ~200ms at 5ms sleep

        import sounddevice as sd
        stream = None

        try:
            stream = sd.OutputStream(samplerate=24000, channels=1, dtype='float32', blocksize=4800)
            stream.start()
            logger.info("Audio stream opened and started")

            initial_queue_size = self.realtime_client.get_queue_size()
            logger.info(f"Initial audio queue size: {initial_queue_size} chunks")

            while not self._stop_playback.is_set():
                queue_size_before = self.realtime_client.get_queue_size()
                audio_bytes = self.realtime_client.get_response_audio()
                queue_size_after = self.realtime_client.get_queue_size()

                if audio_bytes:
                    empty_count = 0
                    chunks_received += 1
                    total_bytes += len(audio_bytes)
                    logger.info(
                        "Audio playback: chunk %s (%s bytes, total: %s, queue: %s->%s)",
                        chunks_received, len(audio_bytes), total_bytes,
                        queue_size_before, queue_size_after,
                    )

                    audio_array = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32767.0
                    try:
                        if not self._stop_playback.is_set():
                            stream.write(audio_array.reshape(-1, 1))
                    except Exception as e:
                        logger.error(f"Error writing to audio stream: {e}")
                        break
                else:
                    empty_count += 1
                    queue_size = self.realtime_client.get_queue_size()
                    done = self._response_done.is_set()

                    if empty_count <= 5 or empty_count % 50 == 0:
                        logger.info(
                            "Empty read %s, queue: %s, response_done: %s",
                            empty_count, queue_size, done,
                        )

                    if done and queue_size == 0 and empty_count >= MAX_EMPTY_AFTER_DONE:
                        logger.info("Response done, queue drained -- exiting playback loop")
                        break

                    if not done and empty_count >= MAX_EMPTY_BEFORE_DONE:
                        logger.warning("No audio for %s reads before response.done -- exiting", empty_count)
                        break

                    time.sleep(0.005)

        except Exception as e:
            logger.error(f"Error in audio playback thread: {e}", exc_info=True)
        finally:
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                    logger.info("Audio stream closed")
                except:
                    pass

            if generation == self._playback_generation:
                self.playing_response = False
                self._response_done.clear()
                if self.realtime_session_active:
                    logger.info("STATE: TALKING → LISTENING (playback finished)")
                    self._set_state(RobotState.LISTENING)
            else:
                logger.info(
                    "Skipping state transition from stale playback thread "
                    "(generation=%s, current=%s)",
                    generation, self._playback_generation,
                )

        logger.info(
            "Audio playback thread finished (generation=%s, total: %s chunks, %s bytes)",
            generation, chunks_received, total_bytes,
        )
    
    def _close_session(self):
        """Close Realtime API session and return to READY state."""
        if self.realtime_session_active:
            self.realtime_client.disconnect()
            self.realtime_session_active = False
            self.last_interaction_time = None
            self.playing_response = False
            
            self._set_state(RobotState.READY)
            
            logger.info("Realtime API session closed")
    
    def run(self):
        """Run the main pipeline loop."""
        self._set_state(RobotState.READY)
        
        logger.info("Robot pipeline started - waiting for voice activity...")
        
        # Main loop: stream microphone audio
        for chunk in self.mic.stream_chunks():
            # Check for session timeout
            if self.realtime_session_active and self.last_interaction_time:
                time_since_last = time.time() - self.last_interaction_time
                if time_since_last > self.session_timeout:
                    logger.info(f"Session timeout after {time_since_last:.1f}s - closing session")
                    self._close_session()
            
            # CRITICAL: Don't send audio while TALKING or THINKING.
            # TALKING: prevents feedback loop from robot's own voice.
            # THINKING: prevents overlapping turns that destabilize state ordering.
            current_state = self.state_manager.get_state()
            if current_state in (RobotState.TALKING, RobotState.THINKING):
                continue
            
            # Local VAD detection (cost gate)
            if self.vad.is_speech(chunk):
                logger.debug("VAD: Speech detected")
                if not self.realtime_session_active:
                    logger.info("VAD: Activating Realtime API session...")
                    self.realtime_client.event_handlers.get("input_audio_buffer.speech_started", lambda x: None)({})
                
                if self.realtime_session_active:
                    self.realtime_client.send_audio(chunk, sample_rate=self.mic.rate)
                    logger.debug("VAD: Audio chunk sent to Realtime API (speech)")

                # Feed speech chunks to speaker identifier
                if self.speaker_identifier:
                    self.speaker_identifier.feed(chunk)
            else:
                if self.realtime_session_active:
                    self.realtime_client.send_audio(chunk, sample_rate=self.mic.rate)
                    logger.debug("VAD: Audio chunk sent to Realtime API (silence)")


def main():
    """Main entry point."""
    # Load configuration
    config = load_config()
    
    # Check internet connectivity
    has_internet = check_internet_connectivity()
    if not has_internet:
        logger.error("No internet connectivity. Realtime API requires internet connection.")
        return
    
    # Initialize UI
    state_manager = RobotStateManager()
    ui_config = config.get("ui", {})
    ui_enabled = ui_config.get("enabled", True)
    ui_port = ui_config.get("port", 5000)
    ui_auto_open = ui_config.get("auto_open_browser", True)
    
    web_ui_server = None
    if ui_enabled:
        try:
            web_ui_server = WebUIServer(
                state_manager=state_manager,
                port=ui_port,
                auto_open=ui_auto_open
            )
            web_ui_server.start()
        except Exception as e:
            logger.warning(f"Failed to start robot web UI: {e}. Continuing without UI.")
            ui_enabled = False
    
    # Initialize and run pipeline
    try:
        pipeline = RealtimePipeline(config, state_manager, web_ui_server)
        pipeline.run()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Pipeline error: {e}", exc_info=True)
    finally:
        if web_ui_server:
            web_ui_server.stop()


if __name__ == "__main__":
    main()
