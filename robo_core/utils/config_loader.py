import yaml
import os
from pathlib import Path
from dotenv import load_dotenv

def load_config(config_file="config/settings.yaml"):
    """
    Load configuration from YAML file.
    
    Args:
        config_file: Path to configuration file
        
    Returns:
        Dictionary containing configuration
    """
    config_path = Path(__file__).parent.parent.parent / config_file
    
    if not config_path.exists():
        # Return default config if file doesn't exist
        return get_default_config()
    
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f) or {}
    
    return config

def get_default_config():
    """Return default configuration for Local VAD + OpenAI Realtime API pipeline."""
    return {
        "audio": {
            "sample_rate": 16000,
            "chunk_size": 512
        },
        "vad": {
            "speech_threshold": 0.5
        },
        "realtime": {
            "voice": "alloy",
            "model": "gpt-4o-realtime-preview-2024-12-17"
        },
        "conversation": {
            "session_timeout_seconds": 60
        },
        "ui": {
            "enabled": True,
            "port": 5000,
            "auto_open_browser": True
        }
    }

def load_env_file(env_file=".env"):
    """
    Load environment variables from .env file.
    
    Args:
        env_file: Path to .env file (relative to project root)
        
    Returns:
        True if .env file was loaded, False otherwise
    """
    project_root = Path(__file__).parent.parent.parent
    env_path = project_root / env_file
    
    if env_path.exists():
        load_dotenv(env_path)
        return True
    return False

def get_api_key(env_var_name="OPENAI_API_KEY"):
    """
    Get API key from environment variable.
    First tries to load from .env file, then checks environment.
    
    Args:
        env_var_name: Name of the environment variable
        
    Returns:
        API key string or None if not found
    """
    # Try to load .env file first
    load_env_file()
    
    # Get from environment (either from .env or already set)
    api_key = os.getenv(env_var_name)
    
    # Return None if it's the placeholder value
    if api_key and api_key.strip() and api_key != "your-api-key-here":
        return api_key.strip()
    
    return None

