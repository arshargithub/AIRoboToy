"""
Real-time speaker identification.
Buffers incoming audio, extracts an embedding once enough speech has
accumulated, and matches against enrolled voiceprints.
"""
import logging
import threading
from dataclasses import dataclass
from typing import Callable, Dict, Optional

import numpy as np

from robo_core.identity.speaker_encoder import SpeakerEncoder
from robo_core.identity.speaker_store import SpeakerStore

logger = logging.getLogger(__name__)


@dataclass
class IdentificationResult:
    name: str           # speaker name or "unknown"
    score: float        # cosine similarity (0-1)
    is_known: bool      # True if score > threshold


class SpeakerIdentifier:
    """Buffers audio chunks and identifies the speaker in a background thread."""

    def __init__(
        self,
        encoder: SpeakerEncoder,
        store: SpeakerStore,
        sample_rate: int = 16000,
        min_audio_seconds: float = 2.0,
        similarity_threshold: float = 0.75,
    ):
        self.encoder = encoder
        self.store = store
        self.sample_rate = sample_rate
        self.min_samples = int(min_audio_seconds * sample_rate)
        self.threshold = similarity_threshold

        self._buffer: list[np.ndarray] = []
        self._buffer_samples = 0
        self._lock = threading.Lock()

        self._current_result: Optional[IdentificationResult] = None
        self._identification_pending = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def feed(self, chunk: np.ndarray) -> None:
        """Append an audio chunk to the identification buffer.

        Call this for every chunk during the LISTENING state.
        Once enough audio has accumulated, identification runs automatically
        in a background thread.
        """
        with self._lock:
            self._buffer.append(chunk)
            self._buffer_samples += len(chunk)

            if (
                not self._identification_pending
                and self._buffer_samples >= self.min_samples
            ):
                audio = np.concatenate(self._buffer)
                self._identification_pending = True
                threading.Thread(
                    target=self._identify, args=(audio,), daemon=True
                ).start()

    def reset(self) -> None:
        """Clear the buffer and result for a new turn."""
        with self._lock:
            self._buffer.clear()
            self._buffer_samples = 0
            self._current_result = None
            self._identification_pending = False

    @property
    def result(self) -> Optional[IdentificationResult]:
        """Latest identification result, or None if not yet available."""
        return self._current_result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _identify(self, audio: np.ndarray) -> None:
        """Run embedding extraction + matching (called from background thread)."""
        try:
            embedding = self.encoder.encode(audio, sample_rate=self.sample_rate)
            if embedding is None:
                return

            speakers = self.store.get_all()
            if not speakers:
                logger.info("No enrolled speakers -- cannot identify")
                self._current_result = IdentificationResult("unknown", 0.0, False)
                return

            best_name, best_score = self._match(embedding, speakers)
            is_known = best_score >= self.threshold
            self._current_result = IdentificationResult(
                name=best_name if is_known else "unknown",
                score=best_score,
                is_known=is_known,
            )
            if is_known:
                logger.info(
                    "Speaker identified: %s (score=%.3f)", best_name, best_score
                )
            else:
                logger.info(
                    "Speaker unknown (best=%s, score=%.3f)", best_name, best_score
                )
        except Exception:
            logger.exception("Speaker identification failed")

    @staticmethod
    def _match(
        query: np.ndarray, speakers: Dict[str, np.ndarray]
    ) -> tuple[str, float]:
        """Return (name, cosine_similarity) of the closest enrolled speaker."""
        best_name = ""
        best_score = -1.0
        for name, ref in speakers.items():
            # Both vectors are L2-normalised, so dot product == cosine similarity.
            score = float(np.dot(query, ref))
            if score > best_score:
                best_score = score
                best_name = name
        return best_name, best_score
