#!/usr/bin/env python3
"""
CLI tool for enrolling family members' voiceprints.

Usage:
    python enroll_speaker.py                # interactive enrollment
    python enroll_speaker.py --list         # list enrolled speakers
    python enroll_speaker.py --remove NAME  # remove a speaker
"""
import argparse
import sys
import time

import numpy as np
import sounddevice as sd

from robo_core.identity.speaker_encoder import SpeakerEncoder
from robo_core.identity.speaker_store import SpeakerStore

SAMPLE_RATE = 16000
SEGMENT_SECONDS = 5
NUM_SEGMENTS = 6


def record_segment(duration: float, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Record a single audio segment from the default microphone."""
    print(f"  Recording for {duration} seconds ... ", end="", flush=True)
    audio = sd.rec(
        int(duration * sample_rate),
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
    )
    sd.wait()
    print("done.")
    return audio.flatten()


def enroll(store: SpeakerStore, encoder: SpeakerEncoder) -> None:
    name = input("Enter speaker name (e.g. 'alice'): ").strip()
    if not name:
        print("Name cannot be empty.")
        return

    existing = store.get(name)
    if existing is not None:
        confirm = input(f"'{name}' is already enrolled. Overwrite? [y/N]: ").strip()
        if confirm.lower() != "y":
            print("Cancelled.")
            return

    print(f"\nWe'll record {NUM_SEGMENTS} segments of {SEGMENT_SECONDS}s each.")
    print("Please speak naturally -- read a paragraph, tell a story, etc.")
    print("Vary your tone and pace across segments for a robust voiceprint.\n")

    embeddings: list[np.ndarray] = []
    for i in range(NUM_SEGMENTS):
        input(f"Press Enter to start segment {i + 1}/{NUM_SEGMENTS} ...")
        audio = record_segment(SEGMENT_SECONDS)

        # Silence check
        rms = float(np.sqrt(np.mean(audio ** 2)))
        if rms < 0.005:
            print("  WARNING: Very little audio detected. Make sure the mic is working.")

        emb = encoder.encode(audio)
        if emb is None:
            print("  Segment too short, skipping.")
            continue
        embeddings.append(emb)
        print(f"  Embedding extracted ({len(embeddings)}/{NUM_SEGMENTS})")

    if len(embeddings) < 3:
        print("Not enough valid segments. Please try again.")
        return

    # Centroid (average) embedding, re-normalised
    centroid = np.mean(embeddings, axis=0).astype(np.float32)
    norm = np.linalg.norm(centroid)
    if norm > 0:
        centroid = centroid / norm

    store.enroll(name, centroid, sample_count=len(embeddings))
    print(f"\nSpeaker '{name}' enrolled successfully with {len(embeddings)} samples.")

    # Quick verification
    print("\nLet's verify. Say something for 3 seconds ...")
    time.sleep(0.5)
    verify_audio = record_segment(3)
    verify_emb = encoder.encode(verify_audio)
    if verify_emb is not None:
        score = float(np.dot(verify_emb, centroid))
        print(f"Verification score: {score:.3f}  ", end="")
        if score >= 0.75:
            print("-- MATCH")
        else:
            print("-- low score; consider re-enrolling with clearer audio")


def list_speakers(store: SpeakerStore) -> None:
    speakers = store.list_speakers()
    if not speakers:
        print("No speakers enrolled.")
        return
    print(f"\n{'Name':<20} {'Enrolled':<28} {'Samples'}")
    print("-" * 56)
    for name, enrolled_at, sample_count in speakers:
        print(f"{name:<20} {enrolled_at:<28} {sample_count}")
    print()


def remove_speaker(store: SpeakerStore, name: str) -> None:
    if store.remove(name):
        print(f"Speaker '{name}' removed.")
    else:
        print(f"Speaker '{name}' not found.")


def main():
    parser = argparse.ArgumentParser(description="Enroll or manage speaker voiceprints")
    parser.add_argument("--list", action="store_true", help="List enrolled speakers")
    parser.add_argument("--remove", type=str, metavar="NAME", help="Remove a speaker")
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Path to voiceprint database (default: ~/.johnny/voiceprints.db)",
    )
    args = parser.parse_args()

    store_kwargs = {}
    if args.db:
        store_kwargs["db_path"] = args.db

    store = SpeakerStore(**store_kwargs)

    if args.list:
        list_speakers(store)
        return

    if args.remove:
        remove_speaker(store, args.remove)
        return

    encoder = SpeakerEncoder()
    try:
        enroll(store, encoder)
    except KeyboardInterrupt:
        print("\nEnrollment cancelled.")
        sys.exit(1)


if __name__ == "__main__":
    main()
