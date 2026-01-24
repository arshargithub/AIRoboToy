"""
Simplified robot pipeline using OpenAI Realtime API.
Uses local VAD as a cost gate, then activates Realtime API for seamless voice conversations.
"""
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
        self._stop_playback = threading.Event()  # Event to signal playback thread to stop
        
        # Setup event handlers
        self._setup_event_handlers()
    
    def _setup_event_handlers(self):
        """Setup Realtime API event handlers for state transitions."""
        
        def on_speech_started(event):
            """Local VAD detected speech - transition to LISTENING."""
            logger.info(f"EVENT: input_audio_buffer.speech_started - {event}")
            
            # CRITICAL: Ignore speech detection while robot is speaking
            # This prevents feedback loop where robot's own voice triggers new responses
            current_state = self.state_manager.get_state()
            if current_state == RobotState.TALKING:
                logger.debug("Ignoring speech_started event - robot is currently speaking")
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
            
            # Update state to LISTENING
            logger.info("STATE: READY → LISTENING")
            self.state_manager.set_state(RobotState.LISTENING)
            if self.ui_enabled:
                self.web_ui_server.emit_state_update(RobotState.LISTENING)
        
        def on_input_committed(event):
            """Input audio committed - transition to THINKING."""
            logger.info(f"EVENT: input_audio_buffer.committed - {event}")
            if self.realtime_session_active:
                logger.info("STATE: LISTENING → THINKING")
                self.state_manager.set_state(RobotState.THINKING)
                if self.ui_enabled:
                    self.web_ui_server.emit_state_update(RobotState.THINKING)
                
                # Create response to get audio output
                # The Realtime API should auto-create responses, but let's ensure it
                item_id = event.get("item_id")
                if item_id:
                    logger.info(f"Input committed for item {item_id}, waiting for response...")
        
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
            audio_size = len(event.get("delta", "")) if event.get("delta") else 0
            logger.debug(f"EVENT: response.audio.delta - received {audio_size} bytes of audio")
            
            # IMMEDIATE TRANSITION: Switch to TALKING as soon as we get ANY audio data
            if not self.playing_response and audio_size > 0:
                logger.info("STATE: THINKING → TALKING (audio response started)")
                self.state_manager.set_state(RobotState.TALKING)
                if self.ui_enabled:
                    self.web_ui_server.emit_state_update(RobotState.TALKING)
            
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
                self.response_thread = threading.Thread(target=self._play_response_audio, daemon=True)
                self.response_thread.start()
        
        def on_response_output_audio_delta(event):
            """Response output audio delta received - same handling as audio delta."""
            audio_size = len(event.get("delta", "")) if event.get("delta") else 0
            logger.debug(f"EVENT: response.output_audio.delta - received {audio_size} bytes of audio")
            # Treat same as audio delta
            on_response_audio_delta(event)
        
        def on_response_output_audio(event):
            """Response output audio received - same handling as delta."""
            logger.debug(f"EVENT: response.output_audio")
            # Treat same as audio delta
            on_response_audio_delta(event)
        
        def on_response_done(event):
            """Response complete - transition back to LISTENING."""
            response = event.get("response", {})
            status = response.get("status", "")
            queue_size = self.realtime_client.get_queue_size()
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
            else:
                # For completed responses, DON'T set playing_response = False immediately
                # Let the playback thread drain the queue first
                # It will exit when queue is empty and it's waited long enough
                logger.info(f"Response completed - keeping playback active to drain {queue_size} queued chunks")
            
            # Only set playing_response = False if cancelled, otherwise let thread drain queue
            if status == "cancelled":
                self.playing_response = False
            
            self.last_interaction_time = time.time()
            
            # Let the audio playback thread handle state transitions
            # This prevents conflicting state changes
            if status == "cancelled":
                logger.info("Response cancelled - audio thread will handle state transition")
            else:
                logger.info(f"Response completed - audio thread will transition back when playback finishes")
        
        def on_conversation_end(event):
            """Conversation ended - close session and return to READY."""
            self._close_session()
        
        # Register handlers
        self.realtime_client.on_event("input_audio_buffer.speech_started", on_speech_started)
        self.realtime_client.on_event("input_audio_buffer.committed", on_input_committed)
        self.realtime_client.on_event("response.created", on_response_created)
        self.realtime_client.on_event("response.output_item.added", on_response_output_item_added)
        self.realtime_client.on_event("response.audio.delta", on_response_audio_delta)
        self.realtime_client.on_event("response.output_audio.delta", on_response_output_audio_delta)
        self.realtime_client.on_event("response.output_audio", on_response_output_audio)
        self.realtime_client.on_event("response.done", on_response_done)
        self.realtime_client.on_event("conversation.item.completed", on_conversation_end)
    
    def _play_response_audio(self):
        """Play response audio chunks as they arrive using a continuous stream."""
        logger.info("Audio playback thread started")
        total_bytes = 0
        chunks_received = 0
        empty_count = 0
        max_empty_count = 20   # Ultra-short timeout for instant responsiveness (0.1 seconds)
        
        # Use a single continuous stream for smoother playback
        import sounddevice as sd
        stream = None
        
        try:
            # Open a continuous audio stream with larger blocksize for smoother playback
            # blocksize=4800 = 200ms buffer at 24kHz (reduces jerky playback)
            stream = sd.OutputStream(samplerate=24000, channels=1, dtype='float32', blocksize=4800)
            stream.start()
            logger.info("Audio stream opened and started")
            
            # Log initial queue size
            initial_queue_size = self.realtime_client.get_queue_size()
            logger.info(f"Initial audio queue size: {initial_queue_size} chunks")
            
            # Keep playing until we've drained the queue or stopped
            # Don't exit just because playing_response is False - wait for queue to drain
            while not self._stop_playback.is_set() and empty_count < max_empty_count:
                # Check if we should stop
                if self._stop_playback.is_set():
                    logger.info("Playback thread received stop signal")
                    break
                
                # Get audio chunk from Realtime API
                queue_size_before = self.realtime_client.get_queue_size()
                audio_bytes = self.realtime_client.get_response_audio()
                queue_size_after = self.realtime_client.get_queue_size()
                
                if audio_bytes:
                    empty_count = 0  # Reset empty count
                    chunks_received += 1
                    total_bytes += len(audio_bytes)
                    logger.info(f"Audio playback: received chunk {chunks_received} ({len(audio_bytes)} bytes, total: {total_bytes} bytes, queue: {queue_size_before}->{queue_size_after})")
                    
                    # Convert to numpy array (PCM16, 24kHz)
                    audio_array = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32767.0
                    
                    # Write to stream (non-blocking)
                    try:
                        if not self._stop_playback.is_set():
                            stream.write(audio_array.reshape(-1, 1))
                    except Exception as e:
                        logger.error(f"Error writing to audio stream: {e}")
                        break
                else:
                    empty_count += 1
                    queue_size = self.realtime_client.get_queue_size()
                    
                    # Log first few empty reads to debug
                    if empty_count <= 5 or empty_count % 20 == 0:
                        logger.info(f"Empty read {empty_count}/{max_empty_count}, queue size: {queue_size}, playing_response: {self.playing_response}, stop_playback: {self._stop_playback.is_set()}")
                    
                    # If queue has items but we're getting None, something is wrong
                    if queue_size > 0 and empty_count > 5:
                        logger.warning(f"Queue has {queue_size} chunks but get_response_audio() returned None! This shouldn't happen.")
                    
                    # INSTANT EXIT: As soon as response is done and queue is empty, exit immediately
                    if not self.playing_response and queue_size == 0:
                        logger.info(f"Response done, queue empty - exiting INSTANTLY (zero delay)")
                        break
                    
                    # Ultra-fast fallback: If response is done, wait max 2 reads (20ms) then exit
                    if not self.playing_response and empty_count >= 2:
                        logger.info(f"Response done, waited {empty_count} reads - exiting ultra-fast")
                        break
                    
                    # Shorter delay for faster responsiveness
                    time.sleep(0.005)  # 5ms instead of 10ms
            
        except Exception as e:
            logger.error(f"Error in audio playback thread: {e}", exc_info=True)
        finally:
            # Clean up stream
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                    logger.info("Audio stream closed")
                except:
                    pass
            
            # CRITICAL: Mark playback as finished and transition to LISTENING
            self.playing_response = False
            if self.realtime_session_active:
                logger.info("STATE: TALKING → LISTENING (playback finished)")
                self.state_manager.set_state(RobotState.LISTENING)
                if self.ui_enabled:
                    self.web_ui_server.emit_state_update(RobotState.LISTENING)
        
        logger.info(f"Audio playback thread finished (total: {chunks_received} chunks, {total_bytes} bytes)")
    
    def _close_session(self):
        """Close Realtime API session and return to READY state."""
        if self.realtime_session_active:
            self.realtime_client.disconnect()
            self.realtime_session_active = False
            self.last_interaction_time = None
            self.playing_response = False
            
            self.state_manager.set_state(RobotState.READY)
            if self.ui_enabled:
                self.web_ui_server.emit_state_update(RobotState.READY)
            
            logger.info("Realtime API session closed")
    
    def run(self):
        """Run the main pipeline loop."""
        # Set initial state to READY
        self.state_manager.set_state(RobotState.READY)
        if self.ui_enabled:
            self.web_ui_server.emit_state_update(RobotState.READY)
        
        logger.info("Robot pipeline started - waiting for voice activity...")
        
        # Main loop: stream microphone audio
        for chunk in self.mic.stream_chunks():
            # Check for session timeout
            if self.realtime_session_active and self.last_interaction_time:
                time_since_last = time.time() - self.last_interaction_time
                if time_since_last > self.session_timeout:
                    logger.info(f"Session timeout after {time_since_last:.1f}s - closing session")
                    self._close_session()
            
            # CRITICAL: Don't send audio to Realtime API while robot is speaking
            # This prevents feedback loop where robot's own voice triggers new responses
            current_state = self.state_manager.get_state()
            if current_state == RobotState.TALKING:
                # Robot is speaking - mute microphone input to prevent feedback
                continue
            
            # Local VAD detection (cost gate)
            if self.vad.is_speech(chunk):
                logger.debug("VAD: Speech detected")
                # Speech detected - trigger event handler which will activate Realtime API if needed
                if not self.realtime_session_active:
                    logger.info("VAD: Activating Realtime API session...")
                    # Simulate speech_started event to activate session
                    self.realtime_client.event_handlers.get("input_audio_buffer.speech_started", lambda x: None)({})
                
                # Send audio to Realtime API if session is active
                if self.realtime_session_active:
                    self.realtime_client.send_audio(chunk, sample_rate=self.mic.rate)
                    logger.debug("VAD: Audio chunk sent to Realtime API (speech)")
            else:
                # No speech - if session is active, still send audio (Realtime API handles VAD)
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
