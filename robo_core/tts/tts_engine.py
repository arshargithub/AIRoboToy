from .openai_wrapper import OpenAITTS
from .coqui_wrapper import CoquiTTS

class TTSEngine:
    def __init__(self, offline_mode=False, api_key=None, voice="alloy", model="tts-1", coqui_model_dir="models/tts/coqui_model"):
        """
        Initialize TTS Engine with support for online (OpenAI) and offline (Coqui) modes.
        
        Args:
            offline_mode: If True, use Coqui TTS (offline). If False, use OpenAI TTS (online).
            api_key: OpenAI API key (optional, can use OPENAI_API_KEY env var) - only used in online mode
            voice: Voice to use for OpenAI TTS (alloy, echo, fable, onyx, nova, shimmer)
            model: Model to use for OpenAI TTS (tts-1 for standard, tts-1-hd for higher quality)
            coqui_model_dir: Directory containing Coqui TTS model files - only used in offline mode
        """
        self.offline_mode = offline_mode
        
        if offline_mode:
            try:
                self.engine = CoquiTTS(model_dir=coqui_model_dir)
            except Exception as e:
                raise RuntimeError(f"Failed to initialize Coqui TTS (offline mode): {e}")
        else:
            try:
                self.engine = OpenAITTS(api_key=api_key, voice=voice, model=model)
            except Exception as e:
                raise RuntimeError(f"Failed to initialize OpenAI TTS (online mode): {e}")

    def synthesize(self, text):
        """Synthesize text to speech and return audio array."""
        return self.engine.tts(text)
    
    def synthesize_async(self, text, callback):
        """
        Synthesize text to speech asynchronously.
        
        Args:
            text: Text to synthesize
            callback: Function to call with audio_array when ready
        """
        if hasattr(self.engine, 'tts_async'):
            return self.engine.tts_async(text, callback)
        else:
            # Fallback: synchronous synthesis
            try:
                audio = self.engine.tts(text)
                callback(audio)
            except Exception as e:
                callback(None)
