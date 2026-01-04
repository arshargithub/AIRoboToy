"""
Robot state manager for UI interface.
Tracks the current state of the robot for visual feedback.
"""
from enum import Enum
from threading import Lock
import time

class RobotState(Enum):
    """Robot states for UI animations."""
    READY = "ready"  # Initial state, waiting for voice activity
    LISTENING = "listening"  # Voice detected by local VAD, streaming to Realtime API
    THINKING = "thinking"  # OpenAI processing (ASR + LLM + TTS synthesis)
    TALKING = "talking"  # Playing audio response

class RobotStateManager:
    """Thread-safe state manager for robot UI."""
    
    def __init__(self):
        self._state = RobotState.READY
        self._lock = Lock()
        self._state_change_time = time.time()
        self._last_update_time = time.time()
    
    def set_state(self, state: RobotState):
        """Set the robot state (thread-safe)."""
        with self._lock:
            if self._state != state:
                self._state = state
                self._state_change_time = time.time()
            self._last_update_time = time.time()
    
    def get_state(self) -> RobotState:
        """Get the current robot state (thread-safe)."""
        with self._lock:
            return self._state
    
    def get_state_info(self):
        """Get state information for UI (thread-safe)."""
        with self._lock:
            return {
                "state": self._state.value,
                "state_change_time": self._state_change_time,
                "last_update_time": self._last_update_time
            }
    
    def is_ready(self) -> bool:
        """Check if robot is ready (waiting for voice activity)."""
        return self.get_state() == RobotState.READY
    
    def is_listening(self) -> bool:
        """Check if robot is listening."""
        return self.get_state() == RobotState.LISTENING
    
    def is_thinking(self) -> bool:
        """Check if robot is thinking."""
        return self.get_state() == RobotState.THINKING
    
    def is_talking(self) -> bool:
        """Check if robot is talking."""
        return self.get_state() == RobotState.TALKING



