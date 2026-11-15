#!/usr/bin/env python3
"""Mario's ears. Runs only in the dedicated voice environment (.local/mario-voice), on this laptop.

    voice_worker.py transcribe   one voice session: the words while you speak, then the final text
    voice_worker.py wake         listens to the stream for "Hey Mario" in your voice, and judges
                                 the samples you give while training

The hub owns the microphone and sends audio here as frames on stdin: one letter, a four-byte length
(big-endian), then that many bytes. Audio is 16 kHz signed 16-bit mono. Answers are JSON, one per
line, on stdout.

    P <audio so far>   -> {"partial": text}       quick pass while you are still speaking
    F <whole audio>    -> {"final": text}         careful pass once you have stopped
    V <profile JSON>   -> (nothing)               whose voice to listen for: {"centre": [...], "bar": x}
    A <100 ms audio>   -> now and then {"wake": {"start": sample, "score": x}} or {"heard": {...}}
    R                  -> (nothing)               forget the stream so far (after a pause in it)
    E <one utterance>  -> {"sample": {"text", "phrase", "print", "seconds"}}   a training sample

Hearing the phrase takes three steps, cheapest first: a small detector notices that somebody began
to speak; the speaker model says whether it is the trained voice; only then are the first words
recognised and compared with the phrase. Nothing is written to disk and nothing leaves the laptop.
"""
import json
import struct
import sys
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel

sys.path.insert(0, str(Path(__file__).resolve().parent))
import voice_rules as rules  # noqa: E402

VOICE_DIR = Path(__file__).resolve().parents[2] / ".local" / "mario-voice"
RATE = 16000
LONGEST = RATE * 31            # a session is at most 30 s


def say(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def samples(pcm):
    return np.frombuffer(pcm[:len(pcm) // 2 * 2], dtype="<i2").astype(np.float32) / 32768


class Words:
    def __init__(self):
        self.model = WhisperModel(str(VOICE_DIR / "model"), device="cpu", compute_type="int8", cpu_threads=4,
                                  local_files_only=True)

    def text(self, audio, careful=False):
        if len(audio) < RATE // 5:
            return ""
        segments, _ = self.model.transcribe(audio[-LONGEST:], language="en", beam_size=3 if careful else 1,
                                            vad_filter=True, condition_on_previous_text=False,
                                            without_timestamps=not careful)
        return " ".join(s.text.strip() for s in segments if s.no_speech_prob < 0.6).strip()


class Ear:
    """The stream, a moment at a time: who began to speak, and whether they said the phrase."""
    BEFORE = int(RATE * 0.45)      # the detector notices speech a little after it began
    FIRST, SECOND = 1.3, 2.0       # seconds after it noticed: the first look, and one more
    PHRASE = (int(RATE * 1.1), int(RATE * 1.4))   # from where the utterance began: as long as the phrase takes, said fast or slowly

    def __init__(self, words):
        import sherpa_onnx
        self.words = words
        config = sherpa_onnx.VadModelConfig()
        config.silero_vad.model = str(VOICE_DIR / "wake" / "silero_vad.onnx")
        config.silero_vad.threshold = 0.5
        config.silero_vad.min_silence_duration = 0.3
        config.silero_vad.min_speech_duration = 0.1
        config.silero_vad.window_size = 512
        config.sample_rate = RATE
        self.vad_config = config
        self.sherpa = sherpa_onnx
        self.voices = sherpa_onnx.SpeakerEmbeddingExtractor(sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(VOICE_DIR / "wake" / "speaker.onnx"), num_threads=2))
        self.centre = None
        self.bar = 1.0
        self.reset()

    def reset(self):
        self.vad = self.sherpa.VoiceActivityDetector(self.vad_config, buffer_size_in_seconds=20)
        self.ring = np.zeros(0, np.float32)
        self.total = 0             # samples since the last reset
        self.speaking = False
        self.since = None          # the sample where the current utterance began
        self.noticed = 0
        self.looks = 0

    def profile(self, data):
        centre = data.get("centre")
        self.centre = np.array(centre, np.float32) if centre else None
        self.bar = float(data.get("bar", 1.0))

    def print_of(self, audio):
        stream = self.voices.create_stream()
        stream.accept_waveform(RATE, audio)
        stream.input_finished()
        vector = np.array(self.voices.compute(stream), np.float32)
        size = float(np.linalg.norm(vector))
        return vector / size if size else vector

    def speech_only(self, audio):
        """The spoken parts of a recording, without the quiet around them."""
        vad = self.sherpa.VoiceActivityDetector(self.vad_config, buffer_size_in_seconds=40)
        parts = []
        padded = np.concatenate([audio, np.zeros(RATE // 2, np.float32)])
        for i in range(0, len(padded), 512):
            vad.accept_waveform(padded[i:i + 512])
            while not vad.empty():
                parts.append(np.array(vad.front.samples, np.float32))
                vad.pop()
        return np.concatenate(parts) if parts else np.zeros(0, np.float32)

    def feed(self, audio):
        self.ring = np.concatenate([self.ring, audio])[-RATE * 6:]
        self.total += len(audio)
        self.vad.accept_waveform(audio)
        while not self.vad.empty():
            self.vad.pop()
        speaking = self.vad.is_speech_detected()
        if speaking and not self.speaking and self.since is None:
            self.noticed = self.total
            self.since = max(0, self.total - len(audio) - self.BEFORE)
            self.looks = 0
        self.speaking = speaking
        if self.since is None:
            return
        age = (self.total - self.noticed) / RATE
        if self.looks == 0 and (not speaking or age >= self.FIRST):
            self.looks = 1
            verdict = self.look()
            # someone still saying the phrase slowly gets one more look; anything else is over
            if verdict != "begins" or not speaking:
                self.since = None
        elif self.looks == 1 and (not speaking or age >= self.SECOND):
            self.look()
            self.since = None

    def look(self):
        if self.centre is None:
            return "untrained"
        audio = self.ring[-min(len(self.ring), self.total - self.since):]
        if len(audio) < RATE * 0.45:
            return "short"
        # the voice is judged on the phrase itself, not on whatever follows it in the same breath:
        # training heard only the phrase, and the same words compare best
        score = max(float(self.print_of(audio[:size]) @ self.centre) for size in self.PHRASE)
        if score < self.bar:
            say({"heard": {"why": "voice", "score": round(score, 3)}})
            return "voice"
        text = self.words.text(audio)
        if rules.is_wake(text):
            say({"wake": {"start": int(self.since), "score": round(score, 3)}})
            return "wake"
        say({"heard": {"why": "words", "score": round(score, 3)}})
        return "begins" if rules.BEGINS.match(text) else "words"

    def sample(self, audio):
        """One training sample: what was said, whether it was the phrase, and the voice's print."""
        text = self.words.text(audio, careful=True)
        speech = self.speech_only(audio)
        phrase = rules.only_wake(text) and len(speech) >= RATE * 0.35
        return {"text": text[:120], "phrase": bool(phrase), "seconds": round(len(speech) / RATE, 2),
                "print": [round(float(x), 5) for x in self.print_of(speech)] if phrase else []}


def frames(stream):
    while True:
        head = stream.read(5)
        if len(head) < 5:
            return
        size = struct.unpack(">I", head[1:])[0]
        body = stream.read(size) if size else b""
        if len(body) < size:
            return
        yield head[:1], body


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "transcribe"
    words = Words()
    ear = Ear(words) if mode == "wake" else None
    say({"ready": mode})
    for kind, body in frames(sys.stdin.buffer):
        if kind == b"P":
            say({"partial": words.text(samples(body))})
        elif kind == b"F":
            say({"final": words.text(samples(body), careful=True)})
        elif ear is None:
            continue
        elif kind == b"A":
            ear.feed(samples(body))
        elif kind == b"R":
            ear.reset()
        elif kind == b"V":
            ear.profile(json.loads(body or b"{}"))
        elif kind == b"E":
            say({"sample": ear.sample(samples(body))})


if __name__ == "__main__":
    main()
