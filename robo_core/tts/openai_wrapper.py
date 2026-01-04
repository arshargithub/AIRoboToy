import os
import io
import numpy as np
from openai import OpenAI
from pydub import AudioSegment
import threading

class OpenAITTS:
    def __init__(self, api_key=None, voice="alloy", model="tts-1"):
        """
        Initialize OpenAI TTS.
        
        Args:
            api_key: OpenAI API key. If None, will try to get from OPENAI_API_KEY env var.
            voice: Voice to use (alloy, echo, fable, onyx, nova, shimmer)
            model: Model to use (tts-1 for standard, tts-1-hd for higher quality)
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key required. Set OPENAI_API_KEY env var or pass api_key parameter.")
        
        self.client = OpenAI(api_key=self.api_key)
        self.voice = voice
        self.model = model
        self.sample_rate = 22050  # Match playback.py default

    def tts(self, text):
        """
        Convert text to speech using OpenAI TTS.
        
        Args:
            text: Text to synthesize
            
        Returns:
            numpy array of audio samples (float32, mono, 22050 Hz)
        """
        # Call OpenAI TTS API
        response = self.client.audio.speech.create(
            model=self.model,
            voice=self.voice,
            input=text
        )
        
        # Get audio bytes (MP3 format)
        audio_bytes = response.content
        
        # Optimize: Use faster MP3 decoding
        # Convert MP3 bytes to numpy array
        audio_segment = AudioSegment.from_mp3(io.BytesIO(audio_bytes))
        
        # Optimize: Do all conversions in one pass
        # Convert to mono and resample in single operation if needed
        if audio_segment.channels > 1:
            audio_segment = audio_segment.set_channels(1)
        
        if audio_segment.frame_rate != self.sample_rate:
            audio_segment = audio_segment.set_frame_rate(self.sample_rate)
        
        # Convert to numpy array (float32, normalized to [-1, 1])
        # Use more efficient conversion
        samples = audio_segment.get_array_of_samples()
        audio_array = np.array(samples, dtype=np.float32)
        
        # Normalize from int16 to float32 [-1, 1]
        # Check if it's int16 or already float
        if audio_array.max() > 1.0 or audio_array.min() < -1.0:
            audio_array = audio_array / (2**15)
        
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
