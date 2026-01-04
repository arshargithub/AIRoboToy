import numpy as np
from .whisper_wrapper import WhisperASR

class ASREngine:
    """
    Automatic Speech Recognition Engine using Whisper.
    Converts audio frames to text.
    """
    
    def __init__(self, model_name="base.en", sample_rate=16000, min_audio_length_seconds=0.5):
        """
        Initialize ASR Engine.
        
        Args:
            model_name: Whisper model to use (default: "base.en")
            sample_rate: Audio sample rate (default: 16000 Hz)
            min_audio_length_seconds: Minimum audio length in seconds to process (default: 0.5)
                                     Very short audio segments can cause hallucinations
        """
        self.whisper = WhisperASR(model_name=model_name, sample_rate=sample_rate)
        self.sample_rate = sample_rate
        self.min_audio_length_samples = int(min_audio_length_seconds * sample_rate)

    def _normalize_audio(self, audio_array):
        """
        Normalize and condition audio for better transcription.
        
        Args:
            audio_array: Audio array to normalize
            
        Returns:
            Normalized audio array
        """
        # Remove DC offset (mean subtraction)
        audio_array = audio_array - np.mean(audio_array)
        
        # Normalize to [-1, 1] range with peak normalization
        max_val = np.abs(audio_array).max()
        if max_val > 0:
            # Normalize to 90% of max to avoid clipping
            audio_array = audio_array / max_val * 0.9
        
        return audio_array
    
    def _trim_silence(self, audio_array, threshold_db=-40):
        """
        Trim leading and trailing silence from audio.
        
        Args:
            audio_array: Audio array to trim
            threshold_db: Silence threshold in dB (default: -40)
            
        Returns:
            Trimmed audio array
        """
        if len(audio_array) == 0:
            return audio_array
        
        # Convert threshold to linear scale
        threshold_linear = 10 ** (threshold_db / 20)
        
        # Find first and last non-silent samples
        abs_audio = np.abs(audio_array)
        non_silent = abs_audio > threshold_linear
        
        if not np.any(non_silent):
            # Entire audio is silence, return empty
            return np.array([], dtype=audio_array.dtype)
        
        first_non_silent = np.argmax(non_silent)
        last_non_silent = len(non_silent) - np.argmax(non_silent[::-1]) - 1
        
        # Add small padding to avoid cutting off speech
        padding_samples = int(0.05 * self.sample_rate)  # 50ms padding
        start_idx = max(0, first_non_silent - padding_samples)
        end_idx = min(len(audio_array), last_non_silent + padding_samples)
        
        return audio_array[start_idx:end_idx]

    def transcribe(self, frames):
        """
        Transcribe audio frames to text.
        
        Args:
            frames: List of numpy arrays representing audio frames
            
        Returns:
            Transcribed text as string
        """
        if not frames:
            return ""
        
        # Concatenate all frames into a single audio array
        audio_array = np.concatenate(frames)
        
        # Ensure float32 format
        if audio_array.dtype != np.float32:
            audio_array = audio_array.astype(np.float32)
        
        # Check minimum audio length (prevents hallucinations on very short audio)
        if len(audio_array) < self.min_audio_length_samples:
            return ""  # Too short, likely noise or incomplete
        
        # Normalize audio (remove DC offset, normalize volume)
        audio_array = self._normalize_audio(audio_array)
        
        # Trim leading/trailing silence (can confuse Whisper)
        audio_array = self._trim_silence(audio_array)
        
        # Check again after trimming (might be too short now)
        if len(audio_array) < self.min_audio_length_samples:
            return ""  # Too short after trimming
        
        # Transcribe using Whisper
        return self.whisper.transcribe(audio_array)
