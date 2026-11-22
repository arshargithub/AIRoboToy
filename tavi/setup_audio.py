"""Download public pinned VAD weights and generate a synthetic local reference."""
import hashlib
import json
from pathlib import Path
import subprocess
from urllib.request import urlopen
from .acoustics import MODEL_SHA256

URL = "https://raw.githubusercontent.com/snakers4/silero-vad/v6.2/src/silero_vad/data/silero_vad.onnx"
TEXT = "Hello, I am Tavi. This is a local audio test. You can interrupt me while I am speaking. We are checking whether I can hear your voice over my own speaker. This reference plays entirely on your computer."

def main():
    model = Path(".tavi/models/silero_vad.onnx")
    model.parent.mkdir(parents=True, exist_ok=True)
    if not model.exists():
        with urlopen(URL, timeout=30) as response:
            data = response.read(4_000_000)
        if hashlib.sha256(data).hexdigest() != MODEL_SHA256:
            raise ValueError("Downloaded VAD checksum mismatch")
        model.write_bytes(data)
    if hashlib.sha256(model.read_bytes()).hexdigest() != MODEL_SHA256:
        raise ValueError("Existing VAD checksum mismatch")
    audio = Path(".tavi/audio")
    audio.mkdir(parents=True, exist_ok=True)
    subprocess.run(["/usr/bin/say", "-r", "145", "-o", str(audio / "reference.aiff"), TEXT], check=True)
    subprocess.run(["/usr/bin/afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(audio / "reference.aiff"), str(audio / "reference.wav")], check=True)
    manifest = {"model": "Silero VAD 6.2", "model_sha256": MODEL_SHA256, "source": URL,
                "license": "MIT", "license_source": "https://github.com/snakers4/silero-vad/blob/v6.2/LICENSE",
                "fixture": "macOS local speech synthesis; synthetic, no family recording", "fixture_text": TEXT}
    (audio / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("Local VAD and reference clip ready. No API usage.")

if __name__ == "__main__":
    main()
