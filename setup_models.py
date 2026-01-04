#!/usr/bin/env python3
"""
Optional setup script to download required models.
Run this ONCE when you have internet connectivity to download all models.
After running this, everything will work offline.

Usage:
    python setup_models.py
"""

import os
import sys
from pathlib import Path
import urllib.request

# Model URLs and destinations
MODELS = {
    "llm": {
        "url": "https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf/resolve/main/Phi-3-mini-4k-instruct-q4.gguf",
        "path": "models/llm/phi-3-mini-4k-instruct-q4.gguf",
        "description": "Phi-3-Mini-Instruct 3.8B (Q4 quantized) - Local LLM for wake decisions and responses"
    }
}


def download_file(url: str, destination: Path, description: str):
    """
    Download a file with progress bar.
    
    Args:
        url: URL to download from
        destination: Path where file should be saved
        description: Description of what's being downloaded
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    
    if destination.exists():
        print(f"✓ {description} already exists at {destination}")
        return True
    
    print(f"Downloading {description}...")
    print(f"  URL: {url}")
    print(f"  Destination: {destination}")
    
    try:
        def show_progress(block_num, block_size, total_size):
            downloaded = block_num * block_size
            percent = min(downloaded * 100 / total_size, 100)
            bar_length = 40
            filled = int(bar_length * downloaded / total_size)
            bar = '=' * filled + '-' * (bar_length - filled)
            sys.stdout.write(f'\r  [{bar}] {percent:.1f}% ({downloaded / 1024 / 1024:.1f} MB / {total_size / 1024 / 1024:.1f} MB)')
            sys.stdout.flush()
        
        urllib.request.urlretrieve(url, destination, show_progress)
        print(f"\n✓ Successfully downloaded {description}")
        return True
    except Exception as e:
        print(f"\n✗ Error downloading {description}: {e}")
        print(f"  You can manually download from: {url}")
        print(f"  And save it to: {destination}")
        return False

def main():
    """Download all required models."""
    print("=" * 60)
    print("AI Robot Toy - Model Setup Script")
    print("=" * 60)
    print()
    print("This script will download required models for offline operation.")
    print("You only need to run this ONCE when you have internet connectivity.")
    print()
    
    # Check internet connectivity
    try:
        import socket
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        print("✓ Internet connectivity detected")
    except OSError:
        print("✗ No internet connectivity detected")
        print("  Please connect to the internet and run this script again.")
        sys.exit(1)
    
    print()
    print("Downloading models...")
    print()
    
    success_count = 0
    total_count = len(MODELS)
    
    for model_type, model_info in MODELS.items():
        url = model_info["url"]
        path = Path(model_info["path"])
        description = model_info["description"]
        
        if download_file(url, path, description):
            success_count += 1
        print()
    
    print("=" * 60)
    if success_count == total_count:
        print(f"✓ Successfully downloaded all {total_count} model(s)")
        print()
        print("Setup complete! You can now run the robot offline.")
    else:
        print(f"⚠ Downloaded {success_count}/{total_count} model(s)")
        print()
        print("Some models failed to download. Please check the error messages above")
        print("and download them manually if needed. See README.md for instructions.")
    print("=" * 60)

if __name__ == "__main__":
    main()

