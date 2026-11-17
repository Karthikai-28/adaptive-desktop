"""Bounded local microphone sessions for Home and for Mario over your work (Super+J, "Hey Mario").

No recording files and no cloud transcription. A session starts when you press the key or the
button, or when the "Hey Mario" listener (wake.py, off until you train it) hears you; it ends on a
pause, after 30 seconds, or when the page stops asking about it. A page must keep polling its
opaque session id; closing it releases the microphone. Recognition runs in a separate process
(voice_worker.py) that is killed on cancel or timeout, so no work outlives a discarded request.

While you speak, the audio so far is recognised again and again (about every half second of new
speech), and the page shows those words as they come: `partial` in the status.

Quick by design: a request ends 1.2 s after you stop speaking, and a complete command ("open
Spotify": the hub's `complete` says so) after 0.6 s, with the words already recognised, so no
second pass is needed. The recogniser is told the names of the installed apps (`vocabulary`), so it
hears "Spotify" rather than "spot if I".
"""
import asyncio
import audioop
import json
import secrets
import shutil
import time
from pathlib import Path

import voice_rules as rules

ROOT = Path(__file__).resolve().parents[2]
VOICE_DIR = ROOT / ".local" / "mario-voice"
WORKER = Path(__file__).with_name("voice_worker.py")
FRAME = 3200                     # 100 ms of 16 kHz signed 16-bit mono
PARTIAL_EVERY = FRAME * 5        # recognise again after this much new audio


def mic_argv():
    return ["parec", "--raw", "--format=s16le", "--rate=16000", "--channels=1", "--latency-msec=100"]


class Room:
    """How loud the room is without you, from what has been heard so far: its quietest tenth. A
    frame counts as speech when it is clearly louder than that (a fan or traffic is not speech),
    and never below a fixed floor. 16 kHz signed 16-bit mono, 100 ms frames."""
    FLOOR, TIMES = 350, 2.2

    def __init__(self, settle=0):
        self.settle = settle       # frames after the microphone opens that are not judged
        self.heard = []
        self.floor = 0

    def feed(self, pcm):
        self.heard.append(audioop.rms(pcm, 2))
        ranked = sorted(self.heard)           # the opening thump is loud: it cannot pass for the room
        self.floor = ranked[len(ranked) // 10]

    def bar(self):
        return max(self.FLOOR, self.floor * self.TIMES)

    def loud(self):
        """Each judged frame so far: was it speech, by what is known of the room now."""
        bar = self.bar()
        return [level >= bar for level in self.heard[self.settle:]]

    def level(self):
        """The last frame above the room, 0..1, for the picture. Square root, so ordinary speech
        already moves it and a shout does not clip it."""
        return min(1.0, (max(0, self.heard[-1] - self.floor) / 6000) ** 0.5) if self.heard else 0.0


class Silence:
    """When a request is over: 1.2 s of quiet after speech, 8 s without any, or 30 s in all.
    A microphone that was just opened is not judged for its first 0.6 s: many start with a thump."""
    SETTLE = 6
    PAUSE = 12              # frames of quiet that end a request
    COMMAND_PAUSE = 6       # ... that end one already heard as a complete command

    def __init__(self, settle=0):
        self.room = Room(settle)
        self.frames = self.spoken = self.quiet = 0

    def feed(self, pcm):
        self.frames += 1
        self.room.feed(pcm)
        loud = self.room.loud()
        self.spoken = sum(loud)
        self.quiet = next((i for i, was in enumerate(reversed(loud)) if was), len(loud))
        return self.frames >= 300 or (self.spoken >= 3 and self.quiet >= self.PAUSE) or (not self.spoken and self.frames >= 80)


class Worker:
    """voice_worker.py in the voice environment: frames in, one JSON answer per line out."""
    def __init__(self, mode, env):
        self.mode, self.env = mode, env
        self.proc = None

    async def start(self):
        env = dict(self.env, HF_HUB_OFFLINE="1", HF_HUB_DISABLE_IMPLICIT_TOKEN="1")
        self.proc = await asyncio.create_subprocess_exec(
            str(VOICE_DIR / "venv/bin/python"), str(WORKER), self.mode,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env=env)
        return self

    def send(self, kind, payload=b""):
        self.proc.stdin.write(kind + len(payload).to_bytes(4, "big") + payload)

    def backlog(self):
        return self.proc.stdin.transport.get_write_buffer_size()

    async def read(self):
        line = await self.proc.stdout.readline()
        if not line:
            raise RuntimeError("Local recognition failed. Run scripts/install-mario-voice.sh to repair it.")
        return json.loads(line)

    async def ask(self, kind, payload, key):
        """Send one request and wait for its answer (other lines are skipped)."""
        self.send(kind, payload)
        while True:
            reply = await self.read()
            if key in reply:
                return reply[key]

    async def kill(self):
        proc, self.proc = self.proc, None
        if proc:
            if proc.returncode is None:
                proc.kill()
            await proc.wait()


class Voice:
    def __init__(self, presence, env, complete=None, vocabulary=None):
        """complete(text): is this already a whole command (then the session ends sooner)?
        vocabulary(): names for the recogniser to listen for."""
        self.presence, self.env = presence, env
        self.complete = complete or (lambda text: False)
        self.vocabulary = vocabulary or (lambda: "")
        self.id = None
        self.state = "idle"
        self.text = self.error = self.partial = ""
        self.task = None
        self.proc = None
        self.worker = None
        self.mic = None
        self.touched = 0
        self.finish = False
        self.unclaimed = False   # started by "Hey Mario"; the page that opens next takes it over
        self.level = 0.0     # how loud the last 100 ms were, 0..1: the page draws it while you speak

    def available(self):
        return (shutil.which("parec") and (VOICE_DIR / "venv/bin/python").exists()
                and all((VOICE_DIR / "model" / name).is_file() for name in ("model.bin", "config.json", "tokenizer.json")))

    def busy(self):
        return bool(self.task and not self.task.done())

    async def start(self, mic=None, prefill=b"", wake=False):
        """mic: a microphone someone else already holds (the "Hey Mario" listener lends its own),
        with `get()` for the next 100 ms and `release()`. prefill: what was said just before."""
        if self.busy():
            if self.unclaimed and not wake:
                self.unclaimed = False
                self.touched = time.monotonic()
                if mic:
                    mic.release()
                return {"id": self.id, "state": self.state, "wake": True}
            if mic:
                mic.release()
            return {"error": "Mario is already listening or recognizing. Finish or cancel that session first."}
        if not self.available():
            if mic:
                mic.release()
            return {"error": "Voice needs setup on this laptop: run scripts/install-mario-voice.sh."}
        self.id = secrets.token_urlsafe(24)
        self.state, self.text, self.error, self.partial = "listening", "", "", ""
        self.finish, self.level, self.unclaimed = False, 0.0, bool(wake)
        # a session "Hey Mario" started waits a little longer for its page: it may have to open first
        self.touched = time.monotonic() + (6 if wake else 0)
        self.task = asyncio.create_task(self.run(mic, bytes(prefill), bool(wake)))
        return {"id": self.id, "state": self.state}

    async def command(self, action, sid):
        if not self.id or sid != self.id:
            return {"error": "This microphone session has ended. Press Talk to Mario again."}
        self.touched = max(self.touched, time.monotonic())
        if action == "cancel":
            await self.close()
            self.state, self.text, self.partial = "cancelled", "", ""
        elif action == "finish":
            self.finish = True
        return {"state": self.state, "text": self.text, "error": self.error, "partial": self.partial,
                "level": round(self.level, 3) if self.state == "listening" else 0}

    async def kill(self):
        proc, self.proc = self.proc, None
        if proc:
            if proc.returncode is None:
                proc.kill()
            await proc.wait()
        worker, self.worker = self.worker, None
        if worker:
            await worker.kill()
        mic, self.mic = self.mic, None
        if mic:
            mic.release()

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        await self.kill()

    def alive(self, what):
        if time.monotonic() - self.touched > 5:
            raise RuntimeError(f"{what} because the page disconnected.")

    async def run(self, mic=None, prefill=b"", wake=False):
        pcm = bytearray(prefill)
        gate = Silence(0 if mic else Silence.SETTLE)      # a lent microphone has been open for a while
        self.mic = mic
        looking = None           # the recognition pass that is running while you speak
        try:
            await self.presence("listening", "Microphone on · pause to send")
            env = self.env()
            # the recogniser loads while you begin to speak
            self.worker = await Worker("transcribe", env).start()
            try:
                self.worker.send(b"H", str(self.vocabulary() or "")[:600].encode())
            except Exception:  # noqa: BLE001  no names: it still hears everything else
                pass
            if mic is None:
                self.proc = await asyncio.create_subprocess_exec(
                    *mic_argv(), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env=env)
            asked = 0
            heard_upto = -1          # how much of the audio the words in self.partial cover
            whole = False            # the partial is a complete command covering all the speech
            while not self.finish:
                self.alive("Microphone stopped")
                chunk = await asyncio.wait_for(mic.get() if mic else self.proc.stdout.readexactly(FRAME), timeout=3)
                pcm.extend(chunk)
                done = gate.feed(chunk)
                self.level = gate.room.level()
                if looking and looking.done():
                    words, looking = looking.result(), None
                    self.partial = (rules.strip_wake(words) if wake else words)[:4000]
                    heard_upto = asked
                # what was said ends where the quiet began; words heard past that point cover it all
                spoke_until = len(pcm) - gate.quiet * FRAME
                covered = gate.spoken >= 3 and heard_upto >= spoke_until + 2 * FRAME
                if covered and gate.quiet >= Silence.COMMAND_PAUSE and self.partial and self.complete(self.partial):
                    whole = True
                    break
                # look again only when there is speech the last look did not cover, and once the
                # speaking stops, at once rather than half a second later
                due = asked < spoke_until + 2 * FRAME and (len(pcm) - asked >= PARTIAL_EVERY or gate.quiet >= 3)
                if not looking and (gate.spoken or prefill) and due:
                    asked = len(pcm)
                    looking = asyncio.create_task(self.worker.ask(b"P", bytes(pcm), "partial"))
                # "Hey Mario, what's the weather" in one breath: the request was over before the
                # session began, so there is no new speech to wait for
                if done or (wake and not gate.spoken and gate.quiet >= Silence.PAUSE and self.partial):
                    break
            await self.release_mic()
            if gate.spoken < 3 and not (wake and prefill):
                raise RuntimeError("No speech heard. Check your input device in Sound settings and try again.")
            self.state = "transcribing"
            await self.presence("thinking", "Recognizing speech locally")
            deadline = time.monotonic() + 90
            if whole:
                # a complete command, already recognised to the end: no second pass
                words = self.partial
            else:
                if looking:
                    await self.wait_for(looking, deadline)
                looking = asyncio.create_task(self.worker.ask(b"F", bytes(pcm), "final"))
                await self.wait_for(looking, deadline)
                words, looking = looking.result(), None
                words = rules.strip_wake(words) if wake else words
            self.text = words.strip()[:4000]
            if self.text:
                self.state = "done"
            elif wake:
                self.state = "silent"        # "Hey Mario" and then nothing: no error, Mario steps back
            else:
                raise RuntimeError("I couldn't make out the words. Please try again.")
        except asyncio.CancelledError:
            self.state, self.text, self.partial = "cancelled", "", ""
            raise
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            self.state, self.error = "error", "Microphone unavailable. Check your input device in Sound settings."
        except Exception as exc:
            self.state, self.error = "error", str(exc)[:220]
        finally:
            pcm.clear()
            self.level = 0.0
            self.unclaimed = False
            if looking and not looking.done():
                looking.cancel()
                await asyncio.gather(looking, return_exceptions=True)
            await self.kill()
            await self.presence("ready")

    async def release_mic(self):
        proc, self.proc = self.proc, None
        if proc:
            if proc.returncode is None:
                proc.kill()
            await proc.wait()
        mic, self.mic = self.mic, None
        if mic:
            mic.release()

    async def wait_for(self, pending, deadline):
        while not pending.done():
            if time.monotonic() > deadline:
                raise RuntimeError("Recognition took too long. Try a shorter command.")
            self.alive("Recognition cancelled")
            await asyncio.wait({pending}, timeout=0.3)
        pending.result()
