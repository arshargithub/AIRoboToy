import subprocess
import tempfile
import numpy as np
from scipy.io import wavfile

class WhisperCpp:
    def __init__(self, model="models/asr/whisper-base.en.bin"):
        self.model = model
        self.sample_rate = 16000

    def _write_wav(self, filepath, audio_bytes):
        """Convert audio bytes to numpy array and write as WAV file."""
        audio_array = np.frombuffer(audio_bytes, dtype=np.float32)
        wavfile.write(filepath, self.sample_rate, audio_array)

    def transcribe(self, audio_bytes):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav_path = f.name
            self._write_wav(wav_path, audio_bytes)

            result = subprocess.check_output([
                "whisper-cli",
                "--model", self.model,
                "--file", wav_path,
                "--output_format", "txt"
            ])
            return result.decode("utf-8").strip()
