# AIRoboToy

Johnny Robot - AI-powered conversational robot using OpenAI Realtime API.

## Overview

Real-time voice interaction robot with:
- Voice Activity Detection (VAD)
- OpenAI Realtime API integration
- Web-based UI with retro animations
- Audio playback and microphone streaming

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Configure environment:
   ```bash
   cp .env.example .env
   # Edit .env with your OpenAI API key
   ```

3. Run:
   ```bash
   python run_robot.py
   ```

## Architecture

- **VAD**: Local voice activity detection
- **Realtime API**: OpenAI streaming audio + LLM
- **Audio**: PyAudio for mic input and speaker output
- **UI**: Flask + WebSocket for real-time state visualization

## Memory System

Memory functionality (Hindsight integration) is managed in a separate repository:
- **Hindsight Infrastructure**: [HindsightRoboMemSetup](https://github.com/arshargithub/HindsightRoboMemSetup)
