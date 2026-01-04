import torch
import numpy as np
from silero_vad import load_silero_vad

class VADEngine:
    def __init__(self, speech_threshold=0.5):
        """
        Initialize VAD Engine using Silero VAD model.
        Model will be downloaded on first run and cached for offline use.
        
        Args:
            speech_threshold: Confidence threshold for speech detection (0.0-1.0). 
                            Higher values are more strict and reduce false positives from noise.
                            Default: 0.5
        """
        self.model = load_silero_vad()
        self.model.eval()  # Set to evaluation mode
        self.sample_rate = 16000  # Silero VAD expects 16kHz
        self.speech_threshold = speech_threshold

    def is_speech(self, chunk):
        """
        Determine if audio chunk contains speech.
        
        Args:
            chunk: Audio chunk (numpy array or list)
            
        Returns:
            True if speech detected, False otherwise
        """
        # Convert to tensor if needed
        if isinstance(chunk, np.ndarray):
            audio_tensor = torch.from_numpy(chunk).float()
        else:
            audio_tensor = torch.tensor(chunk, dtype=torch.float32)
        
        # Ensure 1D tensor (flatten if needed)
        if audio_tensor.dim() > 1:
            audio_tensor = audio_tensor.squeeze()
        if audio_tensor.dim() == 0:
            # Single value, not a chunk
            return False
        
        # Silero VAD expects 16kHz sample rate
        # Process with no gradient computation for efficiency
        with torch.no_grad():
            try:
                speech_prob = self.model(audio_tensor, self.sample_rate).item()
                return speech_prob > self.speech_threshold
            except Exception as e:
                # If there's an error (e.g., wrong sample rate), return False
                # In production, you might want to log this
                return False
