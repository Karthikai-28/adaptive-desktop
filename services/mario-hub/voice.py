"""Explicit, bounded local microphone sessions for the WebKit desktop and panel.

No recording files, cloud transcription, or persistent listening. A page must keep polling its
opaque session id; closing it releases the microphone. A separate recognition process is killed
on cancel/timeout so CPU work cannot outlive a discarded request.
"""
import asyncio
import audioop
import json
import os
import secrets
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VOICE_DIR = ROOT / ".local" / "mario-voice"


class Silence:
    """16 kHz signed 16-bit mono, fed in 100 ms frames."""
    def __init__(self):
        self.frames = self.spoken = self.quiet = 0

    def feed(self, pcm):
        self.frames += 1
        if audioop.rms(pcm, 2) >= 350:
            self.spoken += 1
            self.quiet = 0
        else:
            self.quiet += 1
        return self.frames >= 300 or (self.spoken >= 3 and self.quiet >= 18) or (not self.spoken and self.frames >= 80)


class Voice:
    def __init__(self, presence, env):
        self.presence, self.env = presence, env
        self.id = None
        self.state = "idle"
        self.text = self.error = ""
        self.task = None
        self.proc = None
        self.touched = 0
        self.finish = False

    def available(self):
        return (shutil.which("parec") and (VOICE_DIR / "venv/bin/python").exists()
                and all((VOICE_DIR / "model" / name).is_file() for name in ("model.bin", "config.json", "tokenizer.json")))

    async def start(self):
        if self.task and not self.task.done():
            return {"error": "Mario is already listening or recognizing. Finish or cancel that session first."}
        if not self.available():
            return {"error": "Voice needs setup on this laptop: run scripts/install-mario-voice.sh."}
        self.id = secrets.token_urlsafe(24)
        self.state, self.text, self.error = "listening", "", ""
        self.touched, self.finish = time.monotonic(), False
        self.task = asyncio.create_task(self.run())
        return {"id": self.id, "state": self.state}

    async def command(self, action, sid):
        if not self.id or sid != self.id:
            return {"error": "This microphone session has ended. Press Talk to Mario again."}
        self.touched = time.monotonic()
        if action == "cancel":
            await self.close()
            self.state, self.text = "cancelled", ""
        elif action == "finish":
            self.finish = True
        return {"state": self.state, "text": self.text, "error": self.error}

    async def kill(self):
        proc, self.proc = self.proc, None
        if proc:
            if proc.returncode is None:
                proc.kill()
            await proc.wait()

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        await self.kill()

    async def run(self):
        pcm = bytearray()
        gate = Silence()
        try:
            await self.presence("listening", "Microphone on · pause to send")
            env = self.env()
            self.proc = await asyncio.create_subprocess_exec(
                "parec", "--raw", "--format=s16le", "--rate=16000", "--channels=1", "--latency-msec=100",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env=env)
            while not self.finish:
                if time.monotonic() - self.touched > 5:
                    raise RuntimeError("Microphone stopped because the page disconnected.")
                chunk = await asyncio.wait_for(self.proc.stdout.readexactly(3200), timeout=3)
                pcm.extend(chunk)
                if gate.feed(chunk):
                    break
            await self.kill()
            if gate.spoken < 3:
                raise RuntimeError("No speech heard. Check your input device in Sound settings and try again.")
            self.state = "transcribing"
            await self.presence("thinking", "Recognizing speech locally")
            env.update(HF_HUB_OFFLINE="1", HF_HUB_DISABLE_IMPLICIT_TOKEN="1")
            self.proc = await asyncio.create_subprocess_exec(
                str(VOICE_DIR / "venv/bin/python"), str(Path(__file__).with_name("voice_transcribe.py")),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env=env)
            pending = asyncio.create_task(self.proc.communicate(bytes(pcm)))
            try:
                deadline = time.monotonic() + 90
                while not pending.done():
                    if time.monotonic() > deadline:
                        raise RuntimeError("Recognition took too long. Try a shorter command.")
                    if time.monotonic() - self.touched > 5:
                        raise RuntimeError("Recognition cancelled because the page disconnected.")
                    await asyncio.wait({pending}, timeout=0.3)
                out, _ = pending.result()
                if self.proc.returncode:
                    raise RuntimeError("Local recognition failed. Run scripts/install-mario-voice.sh to repair it.")
                self.text = json.loads(out).get("text", "").strip()[:4000]
                if not self.text:
                    raise RuntimeError("I couldn't make out the words. Please try again.")
                self.state = "done"
            finally:
                await self.kill()
                if not pending.done():
                    pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
        except asyncio.CancelledError:
            self.state, self.text = "cancelled", ""
            raise
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            self.state, self.error = "error", "Microphone unavailable. Check your input device in Sound settings."
        except Exception as exc:
            self.state, self.error = "error", str(exc)[:220]
        finally:
            pcm.clear()
            await self.kill()
            await self.presence("ready")
