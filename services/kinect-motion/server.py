#!/usr/bin/env python3
"""Kinect Motion: fitness, body games, room events and the body gamepad, on 127.0.0.1:8793.

Reads everyone's skeletons from the Kinect hub (services/adaptive-air/kinect_hub.py, /api/people,
which it keeps running while it reads) and serves:

    /fitness   Kinect Fitness: workouts, form coaching, rep races, the fitness check, history
    /arcade    Kinect Arcade: body games, and Kinect Pad (your body as a gamepad)
    /room      Kinect Room: who is here, zones, sitting reminders, tracking coverage, events
    /ws        the live state for those pages (one message per hub frame)
    /events    semantic events only, for Mario / Home Assistant: {"event": "exercise_rep", ...}

Nothing leaves this computer unless motion.json names a webhook. Pictures never leave the hub;
this process sees joints only, and keeps results only (store.py). It stops itself a minute after
the last page closes, unless the room monitor or the pad is on.

    server.py [--port 8793] [--demo]      --demo: synthetic people, no Kinect needed
"""

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import engine as enginelib  # noqa: E402
import exercises  # noqa: E402
import pad as padlib  # noqa: E402
import store as storelib  # noqa: E402
import training  # noqa: E402

PORT = 8793
HUB = os.environ.get("KINECT_HUB_URL", "http://127.0.0.1:8792")
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "adaptive-desktop/motion.json"
STATIC = HERE / "static"
IDLE_EXIT = 60.0
HUB_UNIT = "adaptive-kinect.service"


def log(msg):
    print(f"kinect-motion: {msg}", flush=True)


def load_config(path=CONFIG):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def save_config(cfg, path=CONFIG):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2) + "\n")


class Voice:
    """Coaching aloud through speech-dispatcher; one line at a time, never queued up."""

    def __init__(self, on=True):
        self.on = on and shutil.which("spd-say") is not None
        self.proc = None

    def say(self, text):
        if not self.on or not text:
            return
        if self.proc is not None and self.proc.poll() is None:
            return                                   # still speaking: drop rather than pile up
        self.proc = subprocess.Popen(["spd-say", "-w", "-r", "10", text],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Outbox:
    """Semantic events out of the machine, only if asked: a webhook (Home Assistant's webhook
    trigger takes this directly) and/or MQTT through mosquitto_pub when it is installed."""

    KEEP = {"rep", "set", "workout-done", "joined", "left", "room", "paused", "resumed"}

    def __init__(self, cfg):
        self.webhook = cfg.get("webhook")
        self.mqtt = cfg.get("mqtt") if shutil.which("mosquitto_pub") else None

    def semantic(self, e):
        """The research's rule: send `person_2 / squat / repetition_14`, never more."""
        if e["type"] == "room":
            return {k: v for k, v in e.items() if k != "type"}
        if e["type"] == "rep":
            return {"event": "exercise_rep", "player": e["slot"] + 1, "n": e["n"], "score": e["score"]}
        if e["type"] == "set":
            return {"event": "exercise_set", "player": e["slot"] + 1, "exercise": e["exercise"],
                    "reps": e["reps"], "form": e["form"]}
        return {"event": e["type"], **{k: e[k] for k in ("slot",) if k in e}}

    def send(self, events):
        out = [self.semantic(e) for e in events if e["type"] in self.KEEP]
        if not out or not (self.webhook or self.mqtt):
            return out
        threading.Thread(target=self._post, args=(out,), daemon=True).start()
        return out

    def _post(self, items):
        for item in items:
            body = json.dumps(item).encode()
            if self.webhook:
                try:
                    req = urllib.request.Request(self.webhook, body, {"Content-Type": "application/json"})
                    urllib.request.urlopen(req, timeout=2).read()
                except OSError as err:
                    log(f"webhook: {err}")
            if self.mqtt:
                topic = f"{self.mqtt.get('topic', 'kinect')}/{item.get('event', 'event')}"
                subprocess.run(["mosquitto_pub", "-h", self.mqtt.get("host", "localhost"),
                                "-p", str(self.mqtt.get("port", 1883)), "-t", topic, "-m", body.decode()],
                               timeout=3, capture_output=True)


class Service:
    def __init__(self, cfg, store, demo=False):
        self.cfg, self.store, self.demo = cfg, store, demo
        self.engine = enginelib.Engine(store, cfg)
        self.voice = Voice(cfg.get("voice", True))
        self.outbox = Outbox(cfg)
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.hub = {}
        self.snapshot = {"people": [], "players": [], "workout": {"mode": "idle"}}
        self.clients = set()
        self.event_clients = set()
        self.loop = None
        self.pad = None
        self.pad_error = None
        self.last_client = time.monotonic()
        self.hub_error = None

    # -- the hub

    def _hub_up(self):
        try:
            urllib.request.urlopen(HUB + "/api/status", timeout=0.5).read()
            return True
        except OSError:
            return False

    def _start_hub(self):
        if self._hub_up():
            return
        subprocess.run(["systemctl", "--user", "start", HUB_UNIT], capture_output=True)
        for _ in range(30):
            if self._hub_up():
                return
            time.sleep(0.1)

    def run(self):
        """The reading thread: hub state -> engine -> pages, pad, voice."""
        seq, last_start = 0, 0.0
        source = None
        if self.demo:
            import demo
            source = demo.Demo()
        while not self.stop.is_set():
            try:
                if source is not None:
                    time.sleep(1 / 15)                # the hub's pace, then a fresh frame
                    hub = source.next()
                else:
                    if time.monotonic() - last_start > 5 and not self._hub_up():
                        last_start = time.monotonic()
                        self._start_hub()
                    raw = urllib.request.urlopen(f"{HUB}/api/people?after={seq}", timeout=3).read()
                    hub = json.loads(raw)
                    if hub.get("seq") == seq:
                        continue
                    seq = hub.get("seq", 0)
                self.hub_error = None
            except (OSError, ValueError) as err:
                self.hub_error = f"Kinect hub: {err}"
                self.stop.wait(1.0)
                continue
            with self.lock:
                events, lines = self.engine.step(hub)
                snap = self.engine.state(hub)
                snap["hub_error"] = self.hub_error or hub.get("error")
                snap["voice"] = self.voice.on
                snap["pad_error"] = self.pad_error
                self.snapshot = snap
                if self.pad is not None:
                    try:
                        self.pad.send(self.engine.pad_outputs())
                    except OSError as err:
                        self.pad_error = str(err)
            for line in lines:
                self.voice.say(line)
            semantic = self.outbox.send(events)
            if self.loop is not None:
                try:
                    self.loop.call_soon_threadsafe(self._broadcast, snap, events, semantic)
                except RuntimeError:                  # shutting down: the loop is closed
                    return

    def _broadcast(self, snap, events, semantic):
        msg = json.dumps({"state": snap, "events": events})
        for ws in list(self.clients):
            asyncio.ensure_future(self._send(ws, msg, self.clients))
        if semantic:
            for ws in list(self.event_clients):
                for item in semantic:
                    asyncio.ensure_future(self._send(ws, json.dumps(item), self.event_clients))

    @staticmethod
    async def _send(ws, msg, group):
        try:
            await ws.send_str(msg)
        except (ConnectionError, RuntimeError):
            group.discard(ws)

    # -- the pad

    def set_pad(self, profile, slot=0):
        with self.lock:
            if self.pad is not None:
                self.pad.close()
                self.pad = None
            self.engine.pad_profile, self.engine.pad_slot = None, slot
            self.pad_error = None
            if profile:
                ok, why = padlib.available()
                if not ok:
                    self.pad_error = why
                    return False, why
                try:
                    self.pad = padlib.Pad(profile)
                except OSError as err:
                    self.pad_error = str(err)
                    return False, str(err)
                self.engine.pad_profile = profile
        return True, None

    def idle(self):
        if self.clients or self.event_clients or self.pad is not None or self.cfg.get("room_always"):
            self.last_client = time.monotonic()
            return False
        return time.monotonic() - self.last_client > IDLE_EXIT


# ------------------------------------------------------------------ HTTP

def make_app(svc):
    from aiohttp import web

    def page(name):
        async def handler(_request):
            return web.FileResponse(STATIC / f"{name}.html", headers={"Cache-Control": "no-cache"})
        return handler

    async def ws_state(request):
        ws = web.WebSocketResponse(heartbeat=15)
        await ws.prepare(request)
        svc.clients.add(ws)
        await ws.send_str(json.dumps({"state": svc.snapshot, "events": []}))
        try:
            async for _ in ws:
                pass
        finally:
            svc.clients.discard(ws)
        return ws

    async def ws_events(request):
        ws = web.WebSocketResponse(heartbeat=15)
        await ws.prepare(request)
        svc.event_clients.add(ws)
        try:
            async for _ in ws:
                pass
        finally:
            svc.event_clients.discard(ws)
        return ws

    async def body(request):
        try:
            return await request.json()
        except ValueError:
            raise web.HTTPBadRequest(text="JSON body expected")

    async def catalog(_request):
        return web.json_response({"exercises": exercises.describe(),
                                  "plans": [{"key": k, "name": p["name"], "rest": p["rest"],
                                             "steps": [{"exercise": e, "target": n} for e, n in p["steps"]]}
                                            for k, p in training.PLANS.items()],
                                  "check": training.plan("check"), "retest_days": training.RETEST_DAYS})

    async def state(_request):
        return web.json_response(svc.snapshot)

    async def workout(request):
        b = await body(request)
        action, now = b.get("action"), time.time()
        w = svc.engine.workout
        with svc.lock:
            if action == "start":
                mode = b.get("mode", "free")
                if mode in ("free", "challenge") and b.get("exercise") not in exercises.CATALOG:
                    raise web.HTTPBadRequest(text="Unknown exercise")
                if mode == "plan" and b.get("plan") not in training.PLANS:
                    raise web.HTTPBadRequest(text="Unknown workout")
                svc.engine.join_everyone(now)        # Start on the screen: whoever is there plays
                w.start(mode, now, exercise=b.get("exercise"), plan=b.get("plan"),
                        seconds=b.get("seconds"), target=b.get("target"))
            elif action == "pause":
                w.pause(now)
            elif action == "resume":
                w.resume(now)
            elif action == "next":
                w.next(now)
            elif action == "finish":
                w.finish(now)
            else:
                raise web.HTTPBadRequest(text="action: start, pause, resume, next or finish")
        return web.json_response({"ok": True})

    async def player(request):
        b = await body(request)
        slot = int(b.get("slot", 0))
        with svc.lock:
            roster, w = svc.engine.roster, svc.engine.workout
            p = next((p for p in roster.players if p.slot == slot), None)
            if b.get("leave"):
                roster.leave(slot)
            elif "join" in b:
                person = svc.engine.bodies.get(int(b["join"]))
                if person is not None:
                    roster.join(person, time.time())
            if p is not None and "profile" in b:
                p.profile = b["profile"]
                w.users[slot] = b["profile"]
            if "load" in b:
                w.loads[slot] = [x for x in (b["load"] or []) if isinstance(x, dict)]
        return web.json_response({"ok": True})

    async def users(request):
        if request.method == "POST":
            b = await body(request)
            try:
                uid = svc.store.add_user(b.get("name"), b.get("kg"), b.get("height_cm"))
            except ValueError as err:
                raise web.HTTPBadRequest(text=str(err))
            return web.json_response({"id": uid})
        out = []
        for u in svc.store.users():
            out.append({**u, "totals": svc.store.totals(u["id"]), "equipment": svc.store.equipment(u["id"])})
        return web.json_response(out)

    async def user(request):
        uid = int(request.match_info["uid"])
        if request.method == "DELETE":
            svc.store.delete_user(uid)
            return web.json_response({"ok": True})
        b = await body(request)
        svc.store.update_user(uid, **b)
        return web.json_response({"ok": True})

    async def equipment(request):
        b = await body(request)
        if b.get("delete"):
            svc.store.delete_equipment(int(b["delete"]))
        else:
            svc.store.add_equipment(int(b["user"]), b.get("name", ""), float(b["kg"]), int(b.get("hands", 2)))
        return web.json_response({"ok": True})

    async def history(request):
        uid = int(request.query.get("user", "0") or 0)
        return web.json_response({"sessions": svc.store.history(uid), "totals": svc.store.totals(uid),
                                  "checks": svc.store.checks(uid)})

    async def coverage(request):
        if request.method == "POST":
            svc.engine.room.reset_coverage()
        return web.json_response(svc.engine.room.coverage())

    async def recent(_request):
        return web.json_response(list(svc.engine.events)[-60:])

    async def pad(request):
        b = await body(request)
        ok, why = svc.set_pad(b.get("profile"), int(b.get("slot", 0)))
        return web.json_response({"ok": ok, "error": why})

    async def settings(request):
        b = await body(request)
        if "voice" in b:
            svc.voice.on = bool(b["voice"]) and shutil.which("spd-say") is not None
            svc.cfg["voice"] = svc.voice.on
        if "zones" in b and isinstance(b["zones"], list):
            svc.cfg["zones"] = b["zones"]
            svc.engine.room.zones = [z for z in b["zones"] if z.get("name")]
        if "room_always" in b:
            svc.cfg["room_always"] = bool(b["room_always"])
        save_config(svc.cfg)
        return web.json_response({"ok": True})

    async def config(_request):
        return web.json_response({k: svc.cfg.get(k) for k in ("zones", "voice", "room_always",
                                                              "sit_minutes", "webhook")})

    app = web.Application()
    app.router.add_get("/", lambda _r: web.HTTPFound("/fitness"))
    for name in ("fitness", "arcade", "room"):
        app.router.add_get(f"/{name}", page(name))
    app.router.add_static("/static/", STATIC)
    app.router.add_get("/ws", ws_state)
    app.router.add_get("/events", ws_events)
    app.router.add_get("/api/catalog", catalog)
    app.router.add_get("/api/state", state)
    app.router.add_post("/api/workout", workout)
    app.router.add_post("/api/player", player)
    app.router.add_route("*", "/api/users", users)
    app.router.add_route("*", "/api/users/{uid}", user)
    app.router.add_post("/api/equipment", equipment)
    app.router.add_get("/api/history", history)
    app.router.add_route("*", "/api/coverage", coverage)
    app.router.add_get("/api/events", recent)
    app.router.add_post("/api/pad", pad)
    app.router.add_post("/api/settings", settings)
    app.router.add_get("/api/settings", config)
    return app


async def serve(svc, port):
    from aiohttp import web
    svc.loop = asyncio.get_running_loop()
    runner = web.AppRunner(make_app(svc), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    log(f"on http://127.0.0.1:{port}/fitness")
    while not svc.stop.is_set():
        await asyncio.sleep(1.0)
        if svc.idle():
            log("no page open for a minute; stopping")
            svc.stop.set()
    await runner.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--demo", action="store_true", help="synthetic people instead of the Kinect")
    parser.add_argument("--db", help="history file (default ~/.local/share/adaptive-desktop/fitness.db)")
    args = parser.parse_args()
    svc = Service(load_config(), storelib.Store(args.db), demo=args.demo)
    worker = threading.Thread(target=svc.run, name="hub-reader", daemon=True)
    worker.start()
    import signal
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: svc.stop.set())
    try:
        asyncio.run(serve(svc, args.port))
    finally:
        svc.stop.set()
        if svc.pad is not None:
            svc.pad.close()
        worker.join(timeout=3)
    return 0


if __name__ == "__main__":
    sys.exit(main())
