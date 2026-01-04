import whisper
import numpy as np

class WhisperASR:
    """
    Wrapper for OpenAI's Whisper ASR model.
    Works fully offline after initial model download.
    """
    
    def __init__(self, model_name="base.en", sample_rate=16000):
        """
        Initialize Whisper ASR model.
        
        Args:
            model_name: Whisper model to use. Options:
                - "tiny.en", "base.en", "small.en", "medium.en", "large-v2"
                - "tiny", "base", "small", "medium", "large-v2" (multilingual)
                - Default: "base.en" (good balance of speed/accuracy for English)
            sample_rate: Audio sample rate (default: 16000 Hz)
        """
        self.model_name = model_name
        self.sample_rate = sample_rate
        self.model = None
        self._load_model()
    
    def _load_model(self):
        """Load the Whisper model (downloads on first use if not cached)."""
        try:
            self.model = whisper.load_model(self.model_name)
        except Exception as e:
            raise RuntimeError(
                f"Failed to load Whisper model '{self.model_name}': {e}\n"
                f"Make sure openai-whisper is installed: pip install openai-whisper"
            )
    
    def transcribe(self, audio_data):
        """
        Transcribe audio to text.
        
        Args:
            audio_data: Audio data as numpy array (float32) or bytes
            
        Returns:
            Transcribed text as string
        """
        # Convert to numpy array if needed
        if isinstance(audio_data, bytes):
            audio_array = np.frombuffer(audio_data, dtype=np.float32)
        elif isinstance(audio_data, np.ndarray):
            audio_array = audio_data.astype(np.float32)
        else:
            raise ValueError(f"Unsupported audio data type: {type(audio_data)}")
        
        # Ensure audio is 1D
        if audio_array.ndim > 1:
            audio_array = audio_array.flatten()
        
        # Normalize audio to [-1, 1] range if needed
        if audio_array.max() > 1.0 or audio_array.min() < -1.0:
            # Assume audio is in int16 range, normalize to float32
            if audio_array.dtype != np.float32:
                audio_array = audio_array.astype(np.float32)
            if np.abs(audio_array).max() > 1.0:
                audio_array = audio_array / np.abs(audio_array).max()
        
        # Transcribe using Whisper with optimized parameters to reduce hallucinations
        try:
            result = self.model.transcribe(
                audio_array,
                language="en",  # Force English for .en models
                fp16=False,  # Use fp32 for compatibility
                verbose=False,  # Suppress progress output
                temperature=0.0,  # Lower temperature reduces hallucinations (0.0 = deterministic)
                condition_on_previous_text=False,  # Don't condition on previous text to avoid repetition
                compression_ratio_threshold=2.4,  # Reject if compression ratio too high (indicates repetition)
                logprob_threshold=-1.0,  # Reject if average log probability too low (indicates poor quality)
                no_speech_threshold=0.6  # Reject if no_speech_prob too high (indicates silence/noise)
            )
            text = result["text"].strip()
            return text
        except Exception as e:
            raise RuntimeError(f"Whisper transcription failed: {e}")

