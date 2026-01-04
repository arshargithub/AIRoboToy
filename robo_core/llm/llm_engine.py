from .local_llm import LocalLLM
from .openai_llm import OpenAILLM

class LLMEngine:
    def __init__(self, offline_mode=False, api_key=None, model="gpt-4o-mini", local_model_path="models/llm/llama-3b.gguf"):
        """
        Initialize LLM Engine with support for online (OpenAI) and offline (Local) modes.
        
        Args:
            offline_mode: If True, use local LLM (llama-cpp). If False, use OpenAI LLM.
            api_key: OpenAI API key (optional, can use OPENAI_API_KEY env var) - only used in online mode
            model: Model to use for OpenAI (gpt-4o-mini, gpt-4o, etc.) - only used in online mode
            local_model_path: Path to local LLM model file - only used in offline mode
        """
        self.offline_mode = offline_mode
        
        if offline_mode:
            try:
                self.model = LocalLLM(model_path=local_model_path)
            except Exception as e:
                raise RuntimeError(f"Failed to initialize Local LLM (offline mode): {e}")
        else:
            try:
                self.model = OpenAILLM(api_key=api_key, model=model)
            except Exception as e:
                raise RuntimeError(f"Failed to initialize OpenAI LLM (online mode): {e}")

    def generate_reply(self, text):
        """Generate a reply to the input text."""
        return self.model.generate(text)
