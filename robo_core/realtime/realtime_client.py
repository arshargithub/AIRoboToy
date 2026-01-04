"""
OpenAI Realtime API client wrapper.
Handles WebSocket connection, audio streaming, and event processing.
"""
import json
import base64
import numpy as np
import threading
import queue
import websocket
from typing import Callable, Optional, Dict, Any
from openai import OpenAI
import logging

logger = logging.getLogger(__name__)


class RealtimeAPIClient:
    """
    Client for OpenAI Realtime API.
    Manages WebSocket connection, audio streaming, and event handling.
    """
    
    def __init__(self, api_key: str, voice: str = "alloy", model: str = "gpt-4o-realtime-preview-2024-12-17"):
        """
        Initialize Realtime API client.
        
        Args:
            api_key: OpenAI API key
            voice: Voice to use (alloy, echo, fable, onyx, nova, shimmer)
            model: Model to use (default: gpt-4o-realtime-preview-2024-12-17)
        """
        self.api_key = api_key
        self.voice = voice
        self.model = model
        self.client = OpenAI(api_key=api_key)
        
        self.ws = None
        self.connected = False
        self.event_handlers: Dict[str, Callable] = {}
        self.audio_queue = queue.Queue()
        self.response_audio_queue = queue.Queue()
        
        self._audio_thread = None
        self._response_thread = None
        self._running = False
        
    def connect(self):
        """Establish Realtime API WebSocket session."""
        try:
            # WebSocket URL for Realtime API
            ws_url = f"wss://api.openai.com/v1/realtime?model={self.model}"
            
            # Create WebSocket connection with authentication headers
            self.ws = websocket.WebSocketApp(
                ws_url,
                header=[f"Authorization: Bearer {self.api_key}"],
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
                on_open=self._on_open
            )
            
            self.connected = False
            self._running = True
            
            # Start WebSocket in a thread
            self._ws_thread = threading.Thread(target=self._ws_run, daemon=True)
            self._ws_thread.start()
            
            # Wait for connection to be established
            timeout = 10
            elapsed = 0
            while not self.connected and elapsed < timeout:
                threading.Event().wait(0.1)
                elapsed += 0.1
            
            if not self.connected:
                raise ConnectionError("Failed to establish WebSocket connection within timeout")
            
            # Send session configuration
            self._send_config()
            
            # Start threads for audio streaming
            self._audio_thread = threading.Thread(target=self._audio_worker, daemon=True)
            self._audio_thread.start()
            
            logger.info("Realtime API session connected")
            
        except Exception as e:
            logger.error(f"Failed to connect to Realtime API: {e}")
            self._running = False
            raise
    
    def _send_config(self):
        """Send session configuration to Realtime API."""
        config = {
            "type": "session.update",
            "session": {
                "modalities": ["audio", "text"],
                "instructions": self._get_system_instructions(),
                "voice": self.voice,
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.6,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 500
                },
                "temperature": 0.7,
                "max_response_output_tokens": 4096
            }
        }
        logger.info(f"Sending session configuration: model={self.model}, voice={self.voice}")
        self._send_event(config)
    
    def _send_event(self, event: Dict[str, Any]):
        """Send event to Realtime API via WebSocket."""
        if self.ws and self.connected:
            try:
                self.ws.send(json.dumps(event))
            except Exception as e:
                logger.error(f"Error sending event: {e}")
    
    def _on_open(self, ws):
        """WebSocket connection opened."""
        self.connected = True
        logger.info("✓ WebSocket connection opened successfully")
    
    def _on_message(self, ws, message):
        """Handle incoming WebSocket message."""
        try:
            event = json.loads(message)
            event_type = event.get("type", "unknown")
            logger.debug(f"WebSocket message received: {event_type}")
            self._handle_event(event)
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding WebSocket message: {e}, message: {message[:100]}")
        except Exception as e:
            logger.error(f"Error handling WebSocket message: {e}", exc_info=True)
    
    def _on_error(self, ws, error):
        """Handle WebSocket error."""
        logger.error(f"WebSocket error: {error}")
    
    def _on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket close."""
        self.connected = False
        logger.info("WebSocket connection closed")
    
    def _ws_run(self):
        """Run WebSocket in a thread."""
        self.ws.run_forever()
    
    def disconnect(self):
        """Close Realtime API session."""
        self._running = False
        self.connected = False
        
        if self.ws:
            try:
                self.ws.close()
            except:
                pass
            self.ws = None
        
        logger.info("Realtime API session disconnected")
    
    def _get_system_instructions(self) -> str:
        """Get system instructions for the LLM."""
        return """You are Johnny Hugenschmidt, a helpful and friendly robot who talks to children ages 6-9. Your name is 'Johnny Hugenschmidt' and you respond to 'Johnny', 'Hugenschmidt', or 'Johnny Hugenschmidt'. 

You are talking to a child between 6-9 years old, so use simple words, short sentences, and be enthusiastic and friendly. Be encouraging, age-appropriate, and engaging. Keep your responses concise but complete - aim for 2-4 sentences unless more detail is needed. Always finish your thoughts completely and never cut off mid-sentence.

You can respond when:
- Directly addressed: "Hey Johnny", "Johnny", "Johnny Hugenschmidt", etc.
- Referenced indirectly: "I wonder what Johnny thinks", "Johnny would love this", etc.
- Contextually appropriate: Someone seems to be talking to/about you in a way that suggests you should respond

Use your judgment to determine if a response would be natural and helpful. Don't respond to general conversation that doesn't involve you at all. Be moderately responsive - chime in when it's clearly relevant, but don't interrupt every conversation."""
    
    def send_audio(self, audio_chunk: np.ndarray, sample_rate: int = 16000):
        """
        Send audio chunk to Realtime API.
        Audio will be resampled to 24kHz if needed.
        
        Args:
            audio_chunk: Audio samples (numpy array, float32, -1.0 to 1.0)
            sample_rate: Sample rate of audio (default: 16000)
        """
        if not self.connected or not self._running:
            return
        
        # Resample to 24kHz if needed (Realtime API requires 24kHz)
        if sample_rate != 24000:
            try:
                from scipy import signal
                num_samples = int(len(audio_chunk) * 24000 / sample_rate)
                audio_chunk = signal.resample(audio_chunk, num_samples)
            except ImportError:
                logger.error("scipy not available for resampling")
                return
        
        # Convert to int16 PCM
        audio_int16 = (audio_chunk * 32767).astype(np.int16)
        
        # Encode to base64
        audio_base64 = base64.b64encode(audio_int16.tobytes()).decode('utf-8')
        
        # Queue for sending
        try:
            self.audio_queue.put_nowait(audio_base64)
        except queue.Full:
            pass
    
    def on_event(self, event_type: str, handler: Callable):
        """
        Register event handler.
        
        Args:
            event_type: Event type (e.g., 'input_audio_buffer.speech_started')
            handler: Callback function(event_data)
        """
        self.event_handlers[event_type] = handler
    
    def get_response_audio(self) -> Optional[bytes]:
        """
        Get next audio chunk from response (non-blocking).
        
        Returns:
            Audio data (PCM16, 24kHz) or None if no audio available
        """
        try:
            audio = self.response_audio_queue.get_nowait()
            return audio
        except queue.Empty:
            return None
    
    def get_queue_size(self) -> int:
        """Get current size of response audio queue."""
        return self.response_audio_queue.qsize()
    
    def _audio_worker(self):
        """Worker thread to send audio to Realtime API."""
        chunks_sent = 0
        logger.info("Audio worker thread started")
        while self._running and self.connected:
            try:
                audio_base64 = self.audio_queue.get(timeout=0.1)
                if self.ws and self.connected:
                    chunks_sent += 1
                    # Send audio event
                    event = {
                        "type": "input_audio_buffer.append",
                        "audio": audio_base64
                    }
                    self._send_event(event)
                    if chunks_sent % 50 == 0:  # Log every 50 chunks
                        logger.debug(f"Audio worker: sent {chunks_sent} chunks")
            except queue.Empty:
                continue
            except Exception as e:
                if self._running:
                    logger.error(f"Error sending audio: {e}", exc_info=True)
                break
        logger.info(f"Audio worker thread finished (total chunks sent: {chunks_sent})")
    
    def _handle_event(self, event: Dict[str, Any]):
        """Handle incoming event from Realtime API."""
        event_type = event.get("type", "")
        
        # Log events without verbose data (especially audio base64 strings)
        if "audio" in event_type.lower() and "delta" in event_type.lower():
            # For audio delta events, just log the size
            delta_size = len(event.get("delta", ""))
            logger.debug(f"Realtime API event: {event_type} ({delta_size} bytes)")
        elif event_type in ["response.done", "response.created"]:
            # For response events, log key info without full data
            response = event.get("response", {})
            status = response.get("status", "unknown")
            logger.info(f"Realtime API event: {event_type} - status: {status}")
        else:
            # For other events, log type and key fields only
            logger.debug(f"Realtime API event: {event_type}")
        
        # Handle audio response - check multiple possible event types
        # The actual event type is "response.output_audio.delta" not "response.audio.delta"
        if event_type in ["response.audio.delta", "response.output_audio.delta"]:
            audio_base64 = event.get("delta", "")
            if audio_base64:
                try:
                    audio_bytes = base64.b64decode(audio_base64)
                    self.response_audio_queue.put_nowait(audio_bytes)
                    logger.debug(f"Audio delta decoded: {len(audio_bytes)} bytes queued")
                except Exception as e:
                    logger.error(f"Error decoding audio: {e}", exc_info=True)
            else:
                logger.warning(f"{event_type} event received but delta field is empty")
        
        # Also check for response.output_audio event type (without .delta suffix)
        elif event_type == "response.output_audio":
            # Check both "audio" and "delta" fields
            audio_data = event.get("audio", "") or event.get("delta", "")
            if audio_data:
                try:
                    # Audio might be base64 encoded or raw bytes
                    if isinstance(audio_data, str):
                        audio_bytes = base64.b64decode(audio_data)
                    else:
                        audio_bytes = audio_data
                    self.response_audio_queue.put_nowait(audio_bytes)
                    logger.debug(f"Output audio decoded: {len(audio_bytes)} bytes queued")
                except Exception as e:
                    logger.error(f"Error decoding output audio: {e}", exc_info=True)
        
        # Also check if audio is in response.output_item.added or response.output_item.done
        elif event_type == "response.output_item.added":
            item = event.get("item", {})
            if item.get("type") == "message":
                content = item.get("content", [])
                for content_item in content:
                    if content_item.get("type") == "output_audio":
                        # Audio might be in transcript or we need to request it
                        logger.info(f"Output audio item added: {content_item}")
        
        # Check response.done for audio data
        elif event_type == "response.done":
            response = event.get("response", {})
            output = response.get("output", [])
            for item in output:
                if item.get("type") == "message":
                    content = item.get("content", [])
                    for content_item in content:
                        if content_item.get("type") == "output_audio":
                            logger.info(f"Response done contains audio: {content_item}")
                            # Audio might need to be fetched separately or is in a different format
        
        # Call registered event handlers
        if event_type in self.event_handlers:
            try:
                logger.debug(f"Calling handler for event: {event_type}")
                self.event_handlers[event_type](event)
            except Exception as e:
                logger.error(f"Error in event handler for {event_type}: {e}", exc_info=True)
        else:
            logger.debug(f"No handler registered for event: {event_type}")
        
        # Also handle parent event types (e.g., "response.audio" for "response.audio.delta")
        parent_type = ".".join(event_type.split(".")[:-1])
        if parent_type and parent_type in self.event_handlers:
            try:
                logger.debug(f"Calling parent handler for event: {parent_type}")
                self.event_handlers[parent_type](event)
            except Exception as e:
                logger.error(f"Error in parent event handler for {parent_type}: {e}", exc_info=True)

