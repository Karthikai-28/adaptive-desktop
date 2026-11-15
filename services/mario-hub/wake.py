""""Hey Mario": the listener that waits for the phrase in your voice, and the training that teaches
it your voice.

Off until you train it and turn it on (Mario over your work → Hey Mario). While it is on, the hub
keeps the microphone open and passes the sound, in memory, to voice_worker.py (`wake` mode), which
answers only when the trained voice said the phrase. Then the hub starts an ordinary voice session
on the same microphone, beginning with what you said in that breath, and brings Mario up. Nothing
is recorded: the only thing kept is the voiceprint, numbers in voice.json beside Mario's other
data, readable by you alone. The listener pauses while a session has the microphone, while Mario
is speaking, while you train, and it ignores the phrase while the screen is locked.

Training asks for the phrase rules.SAMPLES times. A sample counts when recognition heard the
phrase and nothing else, and it sounds like the samples before it.
"""
import asyncio
import audioop
import collections
import json
import os
import secrets
import shutil
import subprocess
import time

import voice_rules as rules
from voice import FRAME, VOICE_DIR, Room, Silence, Worker, mic_argv

MODELS = ("silero_vad.onnx", "speaker.onnx")
RING = 60                 # frames kept: the breath that held the phrase goes to the session
RETRY_S = 15              # no microphone yet (before login, device unplugged): look again


def screen_locked(env):
    try:
        out = subprocess.run(["gdbus", "call", "--session", "--dest", "org.gnome.ScreenSaver", "--object-path",
                              "/org/gnome/ScreenSaver", "--method", "org.gnome.ScreenSaver.GetActive"],
                             capture_output=True, text=True, timeout=3, env=env).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "true" in out


class Lent:
    """The listener's microphone, lent to a voice session until it gives it back."""
    def __init__(self, wake):
        self.wake = wake
        self.frames = asyncio.Queue()

    async def get(self):
        return await self.frames.get()

    def release(self):
        self.wake.returned(self)


class Wake:
    def __init__(self, env, file, fired, changed, speaking=lambda: False):
        self.env, self.file = env, file
        self.fired, self.changed, self.speaking = fired, changed, speaking
        self.data = self.load()
        self.task = None           # the listener
        self.proc = self.worker = None
        self.lent = None
        self.hearing = False       # microphone open and the worker ready
        self.error = ""
        self.fed = 0               # bytes given to the worker since it last forgot the stream
        self.ring = collections.deque(maxlen=RING)
        self.train = None          # the training session, if one is open
        self.quiet_until = 0

    # ---------------------------------------------------------------- what is kept
    def load(self):
        if not self.file:
            return {}
        try:
            data = json.loads(self.file.read_text())
        except (OSError, ValueError):
            data = {}
        return data if isinstance(data, dict) else {}

    def save(self):
        if not self.file:
            return
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as out:
            json.dump(self.data, out)
        os.replace(tmp, self.file)

    def available(self):
        return bool(shutil.which("parec") and (VOICE_DIR / "venv/bin/python").exists()
                    and (VOICE_DIR / "model" / "model.bin").is_file()
                    and all((VOICE_DIR / "wake" / name).is_file() for name in MODELS))

    def trained(self):
        return bool((self.data.get("profile") or {}).get("centre"))

    def status(self):
        return {"available": self.available(), "trained": self.trained(), "enabled": bool(self.data.get("enabled")),
                "hearing": self.hearing, "training": bool(self.train and self.train["task"] and not self.train["task"].done()),
                "trained_at": self.data.get("trained_at", 0), "error": self.error}

    # ---------------------------------------------------------------- on and off
    async def start(self):
        if self.data.get("enabled") and self.trained() and self.available() and not (self.task and not self.task.done()):
            self.task = asyncio.create_task(self.listen())

    async def stop(self):
        task, self.task = self.task, None
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self.hang_up()

    async def close(self):
        await self.train_cancel()
        await self.stop()

    async def hang_up(self):
        self.hearing = False
        proc, self.proc = self.proc, None
        if proc:
            if proc.returncode is None:
                proc.kill()
            await proc.wait()
        worker, self.worker = self.worker, None
        if worker:
            await worker.kill()

    async def enable(self, on):
        if on and not self.trained():
            return {"error": "Teach Mario your voice first."}
        if on and not self.available():
            return {"error": "Hey Mario needs setup on this laptop: run scripts/install-mario-voice.sh."}
        self.data["enabled"] = bool(on)
        self.save()
        if on:
            await self.start()
        else:
            await self.stop()
        await self.changed()
        return self.status()

    async def forget(self):
        await self.close()
        self.data = {}
        try:
            if self.file:
                self.file.unlink()
        except OSError:
            pass
        await self.changed()
        return self.status()

    # ---------------------------------------------------------------- the listener
    def lend(self):
        """The open microphone, for a voice session; None when the listener is not running (the
        session then opens its own)."""
        if not self.hearing or self.lent:
            return None
        self.lent = Lent(self)
        return self.lent

    def returned(self, lent):
        if self.lent is lent:
            self.lent = None
            self.forget_stream()
            self.quiet_until = time.monotonic() + 1.5

    def forget_stream(self):
        self.fed = 0
        self.ring.clear()
        if self.worker and self.worker.proc:
            self.worker.send(b"R")

    async def listen(self):
        """Keep the microphone and the worker going; either one failing is tried again later."""
        while True:
            try:
                await self.hear()
            except asyncio.CancelledError:
                raise
            except (OSError, RuntimeError, asyncio.TimeoutError, asyncio.IncompleteReadError, ValueError) as exc:
                self.error = str(exc)[:160] or "The microphone is not available."
            finally:
                self.lent = None       # a session reading from it gives up after three quiet seconds
                await self.hang_up()
            await self.changed()
            await asyncio.sleep(RETRY_S)

    async def hear(self):
        env = self.env()
        self.worker = await Worker("wake", env).start()
        ready = await asyncio.wait_for(self.worker.read(), timeout=90)
        if "ready" not in ready:
            raise RuntimeError("The listener did not start.")
        profile = self.data["profile"]
        self.worker.send(b"V", json.dumps({"centre": profile["centre"], "bar": profile["bar"]}).encode())
        self.proc = await asyncio.create_subprocess_exec(
            *mic_argv(), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env=env)
        answers = asyncio.create_task(self.answers())
        self.forget_stream()
        paused = False
        try:
            while True:
                chunk = await asyncio.wait_for(self.proc.stdout.readexactly(FRAME), timeout=5)
                if not self.hearing:
                    self.hearing, self.error = True, ""
                    await self.changed()
                if answers.done():
                    answers.result()
                    raise RuntimeError("The listener stopped.")
                if self.lent:
                    self.lent.frames.put_nowait(chunk)
                    continue
                # Mario's own voice, and the moment after a session, are not for the listener
                if self.speaking() or time.monotonic() < self.quiet_until:
                    paused = True
                    continue
                if paused:
                    paused = False
                    self.forget_stream()
                if self.worker.backlog() > 2_000_000:
                    raise RuntimeError("The listener fell behind.")
                self.worker.send(b"A", chunk)
                self.ring.append((self.fed, chunk))
                self.fed += len(chunk)
        finally:
            answers.cancel()
            await asyncio.gather(answers, return_exceptions=True)

    async def answers(self):
        while True:
            reply = await self.worker.read()
            wake = reply.get("wake")
            if not wake or self.lent:
                continue
            # the session starts with the breath that held the phrase: "Hey Mario, what's the
            # weather" loses nothing
            start = int(wake.get("start", 0)) * 2
            said = b"".join(chunk for at, chunk in self.ring if at + len(chunk) > start)
            lent = self.lend()
            if lent:
                await self.fired(lent, said, wake.get("score"))

    # ---------------------------------------------------------------- training
    async def train_start(self):
        if not self.available():
            return {"error": "Hey Mario needs setup on this laptop: run scripts/install-mario-voice.sh."}
        await self.train_cancel()
        await self.stop()                      # training has the microphone to itself
        self.train = {"id": secrets.token_urlsafe(24), "state": "starting", "step": 0, "of": rules.SAMPLES,
                      "level": 0.0, "message": "", "heard": "", "touched": time.monotonic(), "task": None}
        self.train["task"] = asyncio.create_task(self.training(self.train))
        await self.changed()
        return self.train_view(self.train)

    @staticmethod
    def train_view(t):
        return {k: t[k] for k in ("id", "state", "step", "of", "message", "heard")} | {"level": round(t["level"], 3)}

    async def train_status(self, sid):
        t = self.train
        if not t or sid != t["id"]:
            return {"error": "This training has ended. Start it again."}
        t["touched"] = time.monotonic()
        return self.train_view(t)

    async def train_cancel(self, sid=None):
        t = self.train
        if not t or (sid and sid != t["id"]):
            return {"state": "cancelled"}
        self.train = None
        if t["task"] and not t["task"].done():
            t["task"].cancel()
            await asyncio.gather(t["task"], return_exceptions=True)
        await self.start()
        await self.changed()
        return {"state": "cancelled"}

    async def utterance(self, t, mic, room):
        """One thing said: from the first sound to 0.7 s of quiet, at most 4 s. None if nobody spoke.
        What counts as sound is measured against the room (voice.Room), all through the training."""
        before = collections.deque(maxlen=4)
        said, loud, quiet, waited = bytearray(), 0, 0, 0
        while True:
            if time.monotonic() - t["touched"] > 5:
                raise RuntimeError("Training stopped because the page closed.")
            chunk = await asyncio.wait_for(mic.stdout.readexactly(FRAME), timeout=3)
            room.feed(chunk)
            t["level"] = room.level()
            speaking = len(room.heard) > room.settle and room.heard[-1] >= room.bar()
            if not said:
                waited += 1
                if not speaking:
                    before.append(chunk)
                    if waited >= 120:
                        return None
                    continue
                said.extend(b"".join(before))
            said.extend(chunk)
            loud, quiet = (loud + 1, 0) if speaking else (loud, quiet + 1)
            if quiet >= 7 or len(said) >= FRAME * 40:
                return bytes(said) if loud >= 3 else None

    async def training(self, t):
        prints, misses = [], 0
        worker = mic = None
        try:
            env = self.env()
            worker = await Worker("wake", env).start()
            ready = await asyncio.wait_for(worker.read(), timeout=90)
            if "ready" not in ready:
                raise RuntimeError("Training could not start.")
            mic = await asyncio.create_subprocess_exec(
                *mic_argv(), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env=env)
            room = Room(Silence.SETTLE)
            while len(prints) < rules.SAMPLES:
                t.update(state="say", step=len(prints))
                said = await self.utterance(t, mic, room)
                if said is None:
                    misses += 1
                    t["message"] = "I didn't hear anything. Say “Hey Mario”."
                else:
                    t.update(state="checking", level=0.0)
                    sample = await asyncio.wait_for(worker.ask(b"E", said, "sample"), timeout=60)
                    t["heard"] = sample.get("text", "")
                    if not sample.get("phrase"):
                        misses += 1
                        t["message"] = (f"I heard “{t['heard']}”. Say just “Hey Mario”." if t["heard"]
                                        else "I couldn't make that out. Say “Hey Mario”.")
                    elif not rules.belongs(prints, sample["print"]):
                        misses += 1
                        t["message"] = "That sounded different from before. Say it again in your usual voice."
                    else:
                        prints.append(sample["print"])
                        t.update(step=len(prints), message="")
                if misses >= 8:
                    raise RuntimeError("That did not work this time. Try again somewhere quieter.")
            self.data = {"enabled": True, "trained_at": int(time.time()), "profile": rules.make_profile(prints)}
            self.save()
            t.update(state="done", level=0.0, message="")
        except asyncio.CancelledError:
            raise
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            t.update(state="error", message="Microphone unavailable. Check your input device in Sound settings.")
        except Exception as exc:  # noqa: BLE001
            t.update(state="error", message=str(exc)[:200])
        finally:
            t["level"] = 0.0
            if mic:
                if mic.returncode is None:
                    mic.kill()
                await mic.wait()
            if worker:
                await worker.kill()
        await self.start()
        await self.changed()
