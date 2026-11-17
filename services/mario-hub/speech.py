"""How Mario talks back: a natural voice on this laptop (tts_worker.py, Kokoro), spd-say without it.

for_speech() is pure: it turns an answer written for the screen into words worth hearing (no
Markdown, links or paths read out symbol by symbol). Speaker keeps the voice worker running for the
hub's life, so a reply starts as soon as its first sentence is made; a new reply cuts the last one off.

The voice is "voice" in mario.json: {"engine": "kokoro" | "espeak", "speaker": "am_michael", "speed": 1.0}.
Speakers (Kokoro v1.0): am_michael, am_fenrir, am_puck, bm_george (men); af_heart, af_bella,
bf_emma (women); hm_omega, hf_alpha (Indian English); all are listed in the model's names.txt.
"""
import asyncio
import itertools
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VOICE_DIR = ROOT / ".local" / "mario-voice"
MODEL = VOICE_DIR / "tts" / "kokoro-multi-lang-v1_0"
WORKER = Path(__file__).with_name("tts_worker.py")
DEFAULT = {"engine": "kokoro", "speaker": "am_michael", "speed": 1.0}


def for_speech(text, longest=900):
    """Plain spoken words: Markdown, code, links and paths taken out, ending on a whole sentence."""
    t = str(text or "")
    t = re.sub(r"```.*?(```|$)", " (the code is on screen) ", t, flags=re.S)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)                 # [text](link) -> text
    t = re.sub(r"https?://\S+", "the link", t)
    t = re.sub(r"(?<![\w.])(?:~|\.{1,2})?/[\w.@+-]+(?:/[\w.@+-]+)+/?", "that folder", t)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"^\s{0,3}#{1,6}\s*", "", t, flags=re.M)               # headings
    t = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", t, flags=re.M)        # list markers
    t = re.sub(r"(\*\*|__|\*|_)(?=\S)(.+?)(?<=\S)\1", r"\2", t)       # bold / italic
    t = re.sub(r"\s*\n+\s*", ". ", t.strip())
    t = re.sub(r"\.(\s*\.)+", ".", t)
    t = re.sub(r"([!?:;,])\.", r"\1", t)
    t = re.sub(r"\s+", " ", t).strip(" .") + ("." if t.strip(" .") else "")
    t = re.sub(r"([!?])\.$", r"\1", t)
    if len(t) > longest:
        cut = max(t.rfind(". ", 0, longest), t.rfind("? ", 0, longest), t.rfind("! ", 0, longest))
        t = t[:cut + 1] if cut > longest // 3 else t[:longest].rsplit(" ", 1)[0] + "."
    return t


def settings(cfg):
    v = dict(DEFAULT)
    v.update({k: val for k, val in ((cfg or {}).get("voice") or {}).items() if k in DEFAULT})
    try:
        v["speed"] = min(1.6, max(0.6, float(v["speed"])))
    except (TypeError, ValueError):
        v["speed"] = 1.0
    return v


def available():
    return (VOICE_DIR / "venv" / "bin" / "python").exists() and (MODEL / "model.onnx").exists()


class Speaker:
    """The voice worker, started once and kept. say() returns True once spoken, False when the
    natural voice is not there (the hub then uses spd-say)."""

    def __init__(self, cfg, env):
        self.cfg, self.env = cfg, env
        self.proc = None
        self.voices = []
        self.ids = itertools.count(1)
        self.waiting = {}
        self.reader = None
        self.lock = asyncio.Lock()
        self.current = None

    def wanted(self):
        return settings(self.cfg)["engine"] == "kokoro" and available()

    async def start(self):
        """Load the voice (a couple of seconds, once); True when it is ready."""
        if self.proc and self.proc.returncode is None:
            return True
        if not self.wanted():
            return False
        async with self.lock:
            if self.proc and self.proc.returncode is None:
                return True
            try:
                self.proc = await asyncio.create_subprocess_exec(
                    str(VOICE_DIR / "venv" / "bin" / "python"), str(WORKER), stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env=self.env())
                line = await asyncio.wait_for(self.proc.stdout.readline(), 60)
                self.voices = (json.loads(line or b"{}").get("ready") or {}).get("voices") or []
            except (OSError, ValueError, asyncio.TimeoutError):
                await self.close()
                return False
            self.reader = asyncio.create_task(self.read())
            return True

    async def read(self):
        proc = self.proc
        while proc and proc.returncode is None:
            line = await proc.stdout.readline()
            if not line:
                break
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            done = self.waiting.pop(msg.get("done"), None)
            if done and not done.done():
                done.set_result(msg)
        for fut in self.waiting.values():
            if not fut.done():
                fut.set_result({"error": "the voice stopped"})
        self.waiting.clear()

    def send(self, message):
        self.proc.stdin.write((json.dumps(message) + "\n").encode())

    async def say(self, text, timeout=90):
        text = for_speech(text)
        if not text or not await self.start():
            return False
        v = settings(self.cfg)
        n = next(self.ids)
        fut = asyncio.get_running_loop().create_future()
        self.waiting[n] = fut
        if self.current is not None:
            self.send({"stop": True})       # the newest reply wins
        self.current = n
        self.send({"say": text, "id": n, "voice": v["speaker"], "speed": v["speed"]})
        try:
            await self.proc.stdin.drain()
            msg = await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self.send({"stop": True})
            return True
        except (ConnectionError, RuntimeError):
            return False
        finally:
            if self.current == n:
                self.current = None
        return not msg.get("error")

    async def stop(self):
        if self.proc and self.proc.returncode is None and self.current is not None:
            self.send({"stop": True})

    async def close(self):
        proc, self.proc = self.proc, None
        if proc and proc.returncode is None:
            proc.kill()
            await proc.wait()
        if self.reader:
            self.reader.cancel()
            self.reader = None
