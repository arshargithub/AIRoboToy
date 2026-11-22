"""
ECAPA-TDNN speaker embedding extraction via SpeechBrain.
Converts raw 16 kHz audio into a 192-dimensional voiceprint vector.
"""
import logging
import numpy as np
import torch
from typing import Optional

logger = logging.getLogger(__name__)

# Embedding dimension produced by spkrec-ecapa-voxceleb
EMBEDDING_DIM = 192


class SpeakerEncoder:
    """Wraps SpeechBrain's pre-trained ECAPA-TDNN for speaker embedding extraction."""

    def __init__(
        self,
        model_source: str = "speechbrain/spkrec-ecapa-voxceleb",
        device: str = "cpu",
    ):
        self.model_source = model_source
        self.device = device
        self._classifier = None

    def _load_model(self):
        if self._classifier is not None:
            return
        from speechbrain.inference.speaker import EncoderClassifier

        logger.info("Loading ECAPA-TDNN model from %s ...", self.model_source)
        self._classifier = EncoderClassifier.from_hparams(
            source=self.model_source,
            run_opts={"device": self.device},
        )
        logger.info("ECAPA-TDNN model loaded")

    def encode(self, audio: np.ndarray, sample_rate: int = 16000) -> Optional[np.ndarray]:
        """Extract a speaker embedding from a 16 kHz mono audio segment.

        Args:
            audio: 1-D float32 array of audio samples (range -1.0 to 1.0).
            sample_rate: Must be 16000 (validated, not resampled).

        Returns:
            1-D numpy array of shape (192,), or None if the audio is too short.
        """
        if sample_rate != 16000:
            raise ValueError(f"ECAPA-TDNN requires 16 kHz audio, got {sample_rate}")

        min_samples = sample_rate  # at least 1 second
        if len(audio) < min_samples:
            logger.debug("Audio too short for embedding (%d samples)", len(audio))
            return None

        self._load_model()

        tensor = torch.tensor(audio, dtype=torch.float32).unsqueeze(0)
        with torch.no_grad():
            embedding = self._classifier.encode_batch(tensor)

        # shape: (1, 1, 192) -> (192,)
        vec = embedding.squeeze().cpu().numpy()
        # L2-normalise so cosine similarity == dot product
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec
