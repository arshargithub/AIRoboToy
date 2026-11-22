"""Explicit pinned K preparation/download; no runtime speech or microphone."""
from pathlib import Path
from .kokoro_k import prepare_assets
from .setup_voice_design import install


if __name__=='__main__':
    prepare_assets()
    install(Path(__file__).with_name('kokoro_mlx_manifest.json'),Path('.tavi/models/kokoro-mlx-bf16'))
