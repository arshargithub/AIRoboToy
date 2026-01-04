import numpy as np
import threading
from TTS.api import TTS

class CoquiTTS:
    def __init__(self, model_dir="models/tts/coqui_model"):
        """
        Initialize Coqui TTS for offline use.
        
        Args:
            model_dir: Directory containing Coqui TTS model files
        """
        self.tts = TTS(model_path=model_dir)
        self.sample_rate = 22050  # Match playback.py default

    def tts(self, text):
        """
        Convert text to speech using Coqui TTS.
        
        Args:
            text: Text to synthesize
            
        Returns:
            numpy array of audio samples (float32, mono, 22050 Hz)
        """
        # Coqui TTS returns audio as numpy array
        audio_array = self.tts.tts(text)
        
        # Ensure it's a numpy array
        if not isinstance(audio_array, np.ndarray):
            audio_array = np.array(audio_array, dtype=np.float32)
        
        # Ensure float32 dtype
        audio_array = audio_array.astype(np.float32)
        
        # Ensure mono (single channel)
        if len(audio_array.shape) > 1:
            audio_array = audio_array[:, 0] if audio_array.shape[1] > 1 else audio_array.flatten()
        
        # Normalize to [-1, 1] if needed
        if audio_array.max() > 1.0 or audio_array.min() < -1.0:
            audio_array = audio_array / np.max(np.abs(audio_array))
        
        return audio_array
    
    def tts_async(self, text, callback):
        """
        Convert text to speech asynchronously.
        
        Args:
            text: Text to synthesize
            callback: Function to call with audio_array when ready
        """
        def _synthesize():
            try:
                audio_array = self.tts(text)
                callback(audio_array)
            except Exception as e:
                # Call callback with None on error
                callback(None)
        
        thread = threading.Thread(target=_synthesize, daemon=True)
        thread.start()
        return thread
