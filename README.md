# AI Robot Toy

An AI-powered robot toy with natural conversation capabilities, supporting both online (OpenAI) and offline (local) modes.

## Features

- **Natural Conversation Detection**: Uses local LLM to detect when the robot should respond (no wake word required)
- **Voice Activity Detection (VAD)**: Detects speech segments using Silero VAD
- **Speech-to-Text (ASR)**: Transcribes speech using OpenAI Whisper (fully offline after initial model download)
- **Large Language Model (LLM)**: 
  - Online: OpenAI GPT-4o-mini for high-quality responses
  - Offline: Phi-3-Mini-Instruct 1.3B for wake decisions and fallback responses
- **Text-to-Speech (TTS)**:
  - Online: OpenAI TTS
  - Offline: Coqui TTS
- **Automatic Mode Switching**: Automatically switches between online/offline based on internet connectivity

## Requirements

- Python 3.11
- Raspberry Pi 5 (recommended) or Raspberry Pi 4
- Microphone
- Speakers/headphones

## Setup

### 1. Clone and Install Dependencies

```bash
# Clone the repository
git clone <your-repo-url>
cd AIRoboToy

# Create virtual environment
python3.11 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Download Models (One-Time Setup)

You need to download the required models. This only needs to be done **once** when you have internet connectivity. After this, everything works offline.

#### Option A: Automatic Download (Recommended)

Run the setup script:

```bash
python setup_models.py
```

This will download:
- **Phi-3-Mini-Instruct 3.8B (Q4 quantized)**: ~2.2GB - Local LLM for wake decisions and responses

**Note**: Whisper ASR models download automatically on first use (no manual setup needed).

#### Option B: Manual Download

If you prefer to download manually:

1. **LLM Model** (Required for offline mode):
   - Download: [Phi-3-Mini-Instruct 1.3B Q4_K_M](https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf/resolve/main/Phi-3-mini-4k-instruct-1.3B-q4_k_m.gguf)
   - Save to: `models/llm/phi-3-mini-4k-instruct-1.3b-q4_k_m.gguf`

2. **ASR Model** (Whisper):
   - Whisper models download automatically on first use
   - Default model: `base.en` (good balance of speed/accuracy)
   - Models are cached in `~/.cache/whisper/` after first download
   - No manual download needed - works offline after first use

3. **TTS Model** (Coqui - for offline mode):
   - Coqui TTS will download models automatically on first use
   - Or download manually and place in `models/tts/coqui_model/`

### 3. Configure API Keys (Optional - for online mode)

If you want to use OpenAI for responses and TTS:

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and add your OpenAI API key:
   ```
   OPENAI_API_KEY=your-actual-api-key-here
   ```

**Note**: The robot works fully offline without an API key. It will use local LLM and Coqui TTS when offline or when no API key is provided.

### 4. Run the Robot

```bash
python run_robot.py
```

The robot will:
- Continuously listen for speech
- Use the local LLM to decide if it should respond
- Generate responses using OpenAI (if online) or local LLM (if offline)
- Speak responses using OpenAI TTS (if online) or Coqui TTS (if offline)

## Configuration

Edit `config/settings.yaml` to customize:

- **Offline mode**: Force offline mode or auto-detect internet connectivity
- **TTS settings**: Voice selection, model choice
- **LLM settings**: Model selection, max tokens
- **ASR settings**: Whisper model selection (tiny.en, base.en, small.en, etc.)
- **Audio settings**: Sample rate, chunk size
- **VAD settings**: Silence threshold

## How It Works

1. **Continuous Listening**: Microphone continuously captures audio
2. **VAD Detection**: Silero VAD detects when speech is present
3. **Speech Collection**: Collects complete speech segments using endpoint detection
4. **Transcription**: OpenAI Whisper transcribes speech to text (fully offline)
5. **Wake Decision**: Local LLM (Phi-3-Mini-Instruct 3.8B) decides if robot should respond
6. **Response Generation**: 
   - If online: OpenAI GPT-4o-mini generates response
   - If offline: Local LLM generates response
7. **Speech Synthesis**: TTS converts response to audio
8. **Playback**: Audio is played through speakers

## Model Information

### Recommended Models for Raspberry Pi 5

- **Phi-3-Mini-Instruct 3.8B (Q4 quantized)**: 
  - Size: ~2.2GB
  - Speed: ~2-4 seconds per inference
  - Quality: Good for wake decisions and responses
  - **This is the default model**

### Alternative Models

If you want to use a different model, update `config/settings.yaml`:

**LLM Models:**
- **TinyLlama 1.1B**: Faster but lower quality
- **Qwen2.5-1.5B**: Good balance of speed and quality

**ASR Models (Whisper):**
- **tiny.en**: Fastest, lowest accuracy (~39MB)
- **base.en**: Good balance (default, ~74MB)
- **small.en**: Better accuracy, slower (~244MB)
- **medium.en**: High accuracy, slower (~769MB)

## Troubleshooting

### Model Not Found Error

If you see `FileNotFoundError: LLM model file not found`:

1. Run `python setup_models.py` to download models
2. Or manually download the model (see Setup section)
3. Ensure the model path in `config/settings.yaml` matches the downloaded file

### No Internet Connectivity

The robot automatically switches to offline mode when no internet is detected. All features work offline using local models.

### Audio Issues

- Ensure microphone and speakers are properly connected
- Check audio device permissions
- Verify sample rate settings in `config/settings.yaml`

## License

[Add your license here]

## Contributing

[Add contribution guidelines here]

