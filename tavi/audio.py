"""Local PCM pre-roll. Idle frames are bounded and never persisted."""
from collections import deque
from dataclasses import dataclass

@dataclass(frozen=True)
class Frame:
    sequence: int
    pcm: bytes
    sample_rate: int = 16000

    @property
    def samples(self) -> int:
        return len(self.pcm) // 2

class PreRoll:
    def __init__(self, seconds: float = 2, sample_rate: int = 16000):
        if seconds <= 0 or sample_rate <= 0:
            raise ValueError("Invalid pre-roll format")
        self.limit = int(seconds * sample_rate)
        self.sample_rate = sample_rate
        self.frames: deque[Frame] = deque()
        self.samples = 0
        self.last_sequence = -1

    def append(self, frame: Frame) -> None:
        if frame.sample_rate != self.sample_rate or len(frame.pcm) % 2 or not frame.pcm:
            raise ValueError("Expected nonempty mono PCM16 in the declared sample rate")
        if frame.sequence <= self.last_sequence or frame.samples > self.limit:
            raise ValueError("Out-of-order or oversized frame")
        self.last_sequence = frame.sequence
        self.frames.append(frame)
        self.samples += frame.samples
        while self.samples > self.limit:
            self.samples -= self.frames.popleft().samples

    def drain(self) -> tuple[Frame, ...]:
        result = tuple(self.frames)
        self.clear()
        return result

    def clear(self) -> None:
        self.frames.clear()
        self.samples = 0
