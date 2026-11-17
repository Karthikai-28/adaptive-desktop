#!/usr/bin/env python3
"""Mario's voice. Runs only in the voice environment (.local/mario-voice), on this laptop.

A natural neural voice (Kokoro v1.0 through sherpa-onnx; scripts/install-mario-voice.sh puts it in
.local/mario-voice/tts). The model stays loaded, so speaking starts as soon as the first sentence is
made: sentence by sentence, each one played while the next is made. Short replies ("Opening
Spotify.") are kept as sound in the cache folder and play at once the next time.

JSON lines on stdin, one answer per line on stdout:
    {"say": text, "id": n, "voice": "am_michael", "speed": 1.0}  -> {"done": n} when the sound has ended
    {"stop": true}                                               -> the current one ends now: {"done": n, "stopped": true}
First line out: {"ready": {"voices": [...]}}. Nothing is recorded and nothing leaves the laptop.
"""
import hashlib
import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

import numpy as np
import sherpa_onnx

MODEL = Path(os.environ.get("MARIO_TTS_MODEL") or
             Path(__file__).resolve().parents[2] / ".local" / "mario-voice" / "tts" / "kokoro-multi-lang-v1_0")
CACHE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "adaptive-desktop" / "mario-voice"
CACHE_LONGEST = 90          # characters: replies up to this long are kept as sound
CACHE_FILES = 400
RATE = 24000
_out = threading.Lock()


def say(message):
    with _out:
        sys.stdout.write(json.dumps(message) + "\n")
        sys.stdout.flush()


def voices():
    """Speaker names in model order (names.txt is written by the installer from the model's metadata)."""
    try:
        return [n.strip() for n in (MODEL / "names.txt").read_text().split(",") if n.strip()]
    except OSError:
        return []


def load():
    lexicon = ",".join(str(MODEL / f) for f in ("lexicon-us-en.txt",) if (MODEL / f).exists())
    model = sherpa_onnx.OfflineTtsModelConfig(
        kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
            model=str(MODEL / "model.onnx"), voices=str(MODEL / "voices.bin"), tokens=str(MODEL / "tokens.txt"),
            data_dir=str(MODEL / "espeak-ng-data"), lexicon=lexicon, lang="en-us"),
        num_threads=3)
    # one sentence at a time: the first is heard while the rest are still being made
    return sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(model=model, max_num_sentences=1))


def pcm(samples):
    return (np.clip(np.asarray(samples, dtype=np.float32), -1, 1) * 32767).astype("<i2").tobytes()


class Player:
    """pacat, fed from a queue by its own thread, so making the next sentence never waits for the
    sound card. close() waits for the sound to end; kill() ends it now."""

    def __init__(self):
        self.proc = subprocess.Popen(["pacat", "--raw", "--format=s16le", f"--rate={RATE}", "--channels=1",
                                      "--client-name=Mario", "--stream-name=Mario", "--latency-msec=60"],
                                     stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.chunks = queue.Queue()
        self.thread = threading.Thread(target=self.pump, daemon=True)
        self.thread.start()

    def pump(self):
        while True:
            chunk = self.chunks.get()
            if chunk is None:
                break
            try:
                self.proc.stdin.write(chunk)
                self.proc.stdin.flush()
            except (BrokenPipeError, ValueError, OSError):
                break
        try:
            self.proc.stdin.close()
        except OSError:
            pass

    def play(self, chunk):
        self.chunks.put(chunk)

    def close(self, stopped):
        self.chunks.put(None)
        while True:
            if stopped.is_set():
                return self.kill()
            try:
                self.proc.wait(timeout=0.05)
                return
            except subprocess.TimeoutExpired:
                continue

    def kill(self):
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait()


def cache_file(voice, speed, text):
    return CACHE / (hashlib.sha1(f"kokoro-v1.0\0{voice}\0{speed}\0{text}".encode()).hexdigest() + ".s16")


def keep(path, sound):
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(sound)
        tmp.replace(path)
        files = sorted(CACHE.glob("*.s16"), key=lambda p: p.stat().st_mtime)
        for old in files[:-CACHE_FILES]:
            old.unlink(missing_ok=True)
    except OSError:
        pass


def speak(tts, names, job, stopped):
    text = str(job.get("say") or "").strip()
    voice = str(job.get("voice") or "am_michael")
    speed = float(job.get("speed") or 1.0)
    sid = names.index(voice) if voice in names else 0
    cached = cache_file(voice, speed, text) if len(text) <= CACHE_LONGEST else None
    player = Player()
    try:
        if cached and cached.exists():
            player.play(cached.read_bytes())
            cached.touch()
        else:
            made = []

            def heard(samples, _progress):
                if stopped.is_set():
                    return 0
                chunk = pcm(samples)
                made.append(chunk)
                player.play(chunk)
                return 1
            tts.generate(text, sid=sid, speed=speed, callback=heard)
            if cached and not stopped.is_set():
                keep(cached, b"".join(made))
    finally:
        player.close(stopped)


def main():
    tts = load()
    names = voices()
    say({"ready": {"voices": names}})
    jobs = queue.Queue()
    stopped = threading.Event()

    def read():
        for line in sys.stdin:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("stop"):
                stopped.set()
            elif msg.get("say"):
                jobs.put(msg)
        jobs.put(None)
        stopped.set()
    threading.Thread(target=read, daemon=True).start()
    while True:
        job = jobs.get()
        if job is None:
            return
        stopped.clear()
        try:
            speak(tts, names, job, stopped)
        except Exception as exc:  # noqa: BLE001  one bad sentence never ends the voice
            say({"done": job.get("id"), "error": str(exc)[:200]})
            continue
        say({"done": job.get("id"), **({"stopped": True} if stopped.is_set() else {})})


if __name__ == "__main__":
    main()
