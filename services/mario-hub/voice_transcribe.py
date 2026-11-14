#!/usr/bin/env python3
"""Recognize bounded raw PCM from stdin; run only in the dedicated voice environment."""
import json
import sys
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel


def main():
    audio = np.frombuffer(sys.stdin.buffer.read(16000 * 2 * 31), dtype="<i2").astype(np.float32) / 32768
    model = WhisperModel(str(Path(__file__).resolve().parents[2] / ".local/mario-voice/model"),
                         device="cpu", compute_type="int8", cpu_threads=4, local_files_only=True)
    segments, _ = model.transcribe(audio, language="en", beam_size=3, vad_filter=True,
                                   condition_on_previous_text=False)
    print(json.dumps({"text": " ".join(s.text.strip() for s in segments if s.no_speech_prob < 0.6)}))


if __name__ == "__main__":
    main()
