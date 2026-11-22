"""Local neural speech gate. PCM is transient; only counters leave this object."""
import hashlib
from pathlib import Path
import time
from uuid import uuid4
from collections import deque
from .audio import Frame, PreRoll

MODEL_SHA256 = "1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3"

class Silero:
    def __init__(self, path: Path, *, wake_backend="baseline"):
        import numpy as np
        import onnxruntime as ort
        if hashlib.sha256(path.read_bytes()).hexdigest() != MODEL_SHA256:
            raise ValueError("VAD model checksum mismatch")
        self.np = np
        options = ort.SessionOptions()
        options.inter_op_num_threads = options.intra_op_num_threads = 1
        self.session = ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])
        self.wake = None
        self.keyword = ''
        self.wake_backend=wake_backend
        if wake_backend == 'custom':
            from .custom_wake import CustomWake
            self.wake=CustomWake()
        elif wake_backend in ('baseline','hey'):
            try:
                from .wake import SherpaWake
                self.wake=SherpaWake(phrase='hey_tavi' if wake_backend=='hey' else 'tavi',variants=wake_backend=='hey')
            except (ImportError, FileNotFoundError):
                pass
        elif wake_backend != 'off':
            raise ValueError('Unknown wake backend')
        self.reset()

    def reset(self):
        self.keyword = ''
        self.speech_recent=deque(maxlen=16)
        if self.wake:
            self.wake.reset()
        self.state = self.np.zeros((2, 1, 128), dtype=self.np.float32)
        self.context = self.np.zeros((1, 64), dtype=self.np.float32)

    def probability(self, pcm: bytes) -> float:
        np = self.np
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32).reshape(1, -1) / 32768
        audio = np.concatenate((self.context, samples), axis=1)
        output, self.state = self.session.run(None, {"input": audio, "state": self.state, "sr": np.array(16000, dtype=np.int64)})
        self.context = samples[:, -64:]
        probability=float(output[0][0]);self.speech_recent.append(probability)
        if self.wake:
            self.keyword=self.wake.feed(pcm,speech_allowed=max(self.speech_recent)>=.5) if self.wake_backend=='custom' else self.wake.feed(pcm)
        return probability

class AcousticSession:
    """Single endpoint lease; ordered 32 ms frames; reset on gaps or stale input."""
    def __init__(self, detector, clock=time.monotonic):
        self.detector = detector
        self.clock = clock
        self.stream_id = None
        self.buffer = PreRoll()
        self.last = 0.0
        self.sequence = -1
        self.high_frames = 0
        self.speech_frames = 0
        self.frames = 0

    def start(self) -> dict:
        self.stop()
        self.stream_id = uuid4().hex
        self.last = self.clock()
        return {"stream_id": self.stream_id, "sample_rate": 16000, "frame_samples": 512, "wake_ready": bool(getattr(self.detector, "wake", None)), "wake_backend": getattr(self.detector, "wake_backend", "baseline")}

    def stop(self):
        self.stream_id = None
        self.buffer = PreRoll()
        self.detector.reset()
        self.high_frames = self.frames = self.speech_frames = 0
        self.sequence = -1

    def expire(self):
        if self.stream_id is not None and self.clock() - self.last > 2:
            self.stop()

    def feed(self, stream_id: str, sequence: int, pcm: bytes) -> dict:
        if stream_id != self.stream_id or self.stream_id is None:
            raise ValueError("Audio endpoint lease expired")
        if self.clock() - self.last > 2 or type(sequence) is not int or sequence != self.sequence + 1 or len(pcm) != 1024:
            self.stop()
            raise ValueError("Audio gap, backlog, or invalid PCM; restart capture")
        started = self.clock()
        probability = self.detector.probability(pcm)
        self.buffer.append(Frame(sequence, pcm))
        self.sequence = sequence
        self.last = self.clock()
        self.high_frames = self.high_frames + 1 if probability >= .65 else 0
        speech = self.high_frames >= 2
        self.frames += 1
        self.speech_frames += int(speech)
        return {"sequence": sequence, "probability": probability, "speech": speech,
                "keyword": getattr(self.detector, "keyword", ""),
                "wake_score": getattr(getattr(self.detector, "wake", None), "score", None),
                "frames": self.frames, "speech_frames": self.speech_frames,
                "preroll_samples": self.buffer.samples, "inference_ms": (self.clock() - started) * 1000}
