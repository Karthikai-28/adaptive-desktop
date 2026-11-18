#!/usr/bin/env python3
"""Kinect Motion: fitness, body games, room events and the body gamepad, on 127.0.0.1:8793.

Reads everyone's skeletons from the Kinect hub (services/adaptive-air/kinect_hub.py, /api/people,
which it keeps running while it reads) and serves:

    /app       the Kinect app: Home, Fitness, Games, Camera, Room, Scan and History in one page
               (apps/kinect/kinect.py shows it in a window). The old pages' addresses (/fitness,
               /arcade, /room) open the same sections of it.
    /hub/...   the hub's own pictures, point cloud and controls, through this origin (the
               Camera section), so the page has one address
    /ws        the live state for those pages (one message per hub frame, and from the watchdog
               between frames while a game runs or tracking is lost)
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
TICK = 1 / 30           # s between watchdog ticks
ACTIVITY_HOLD = 3.0     # s the hub keeps infrared without colour checks after each reminder


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
        self.activity_sent = 0.0
        import scan as scanlib
        self.scanner = scanlib.Scanner(self._hub_post, self._scan_event)
        self.frames = None

    def _scan_event(self, event):
        if self.loop is not None:
            snap = self.snapshot
            try:
                self.loop.call_soon_threadsafe(self._broadcast, snap, [event], [])
            except RuntimeError:
                pass

    def depth_now(self):
        """The newest depth frame straight from the hub's shared memory, with its own mode and
        lens: (depth, mode, intrinsics) or None. For the scan's framing view."""
        sys.path.insert(0, str(HERE.parents[0] / "adaptive-air"))
        import frames as frameslib
        import kinect as kinectlib
        try:
            if self.frames is None:
                self.frames = frameslib.Reader()
            _, depth, head = self.frames.read(timeout=1.0, newer=False)
        except OSError:
            self.frames = None
            return None
        return depth.copy(), head["mode"], kinectlib.intrinsics(head["mode"])

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
            import demoroom
            source = demoroom.Demo()
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
                self.hub = hub
                events, lines = self.engine.step(hub)
                snap = self._snap(hub)
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

    def watchdog(self):
        """Between frames: the engine's freshness and game clock, the pad's release, and the
        reminder that keeps the hub from leaving infrared during a workout or game."""
        last_send = 0.0
        while not self.stop.wait(TICK):
            now = time.time()
            with self.lock:
                events = self.engine.tick(now)
                if self.pad is not None:
                    try:
                        self.pad.send(self.engine.pad_outputs())
                    except OSError as err:
                        self.pad_error = str(err)
                live = self.engine.live()
                moving = (self.engine.game is not None and not self.engine.game.over) or \
                    any(self.engine.lost.values()) or not self.engine.fresh
                snap = None
                if events or (moving and now - last_send > 1 / 15) or now - last_send > 1.0:
                    snap = self._snap(self.hub)
                    self.snapshot = snap
                    last_send = now
            if time.monotonic() - getattr(self, "scan_kept", 0.0) > 2.0:
                self.scan_kept = time.monotonic()
                threading.Thread(target=self.scanner.keep_alive, daemon=True).start()
            if live and not self.demo and time.monotonic() - self.activity_sent > 1.0:
                self.activity_sent = time.monotonic()
                threading.Thread(target=self._hub_post, args=("activity", ACTIVITY_HOLD), daemon=True).start()
            if events:
                semantic = self.outbox.send(events)
                for line in self.engine._sayings(events, now):
                    self.voice.say(line)
            else:
                semantic = []
            if snap is not None and self.loop is not None:
                try:
                    self.loop.call_soon_threadsafe(self._broadcast, snap, events, semantic)
                except RuntimeError:
                    return

    def _hub_post(self, name, value):
        try:
            req = urllib.request.Request(f"{HUB}/api/{name}", json.dumps({"value": value}).encode(),
                                         {"Content-Type": "application/json"})
            return json.loads(urllib.request.urlopen(req, timeout=1.5).read())
        except (OSError, ValueError):
            return None

    def _snap(self, hub):
        snap = self.engine.state(hub)
        snap["hub_error"] = self.hub_error or hub.get("error")
        snap["voice"] = self.voice.on
        snap["pad_error"] = self.pad_error
        return snap

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

    def http(self):
        """One aiohttp client session for the hub proxy (made in the event loop)."""
        import aiohttp
        if getattr(self, "_http", None) is None or self._http.closed:
            self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5))
        return self._http

    def _hub_status(self):
        try:
            return json.loads(urllib.request.urlopen(HUB + "/api/status", timeout=1.0).read())
        except (OSError, ValueError):
            return None

    def idle(self):
        scanning = self.scanner.job is not None and self.scanner.job.state in ("background", "capturing", "reconstructing")
        if self.clients or self.event_clients or self.pad is not None or self.cfg.get("room_always") or scanning:
            self.last_client = time.monotonic()
            return False
        return time.monotonic() - self.last_client > IDLE_EXIT


# ------------------------------------------------------------------ HTTP

def make_app(svc):
    from aiohttp import web

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
                                  "check": training.plan("check"), "retest_days": training.RETEST_DAYS,
                                  "games": [{"key": g.key, "name": g.name, "tutorial": g.tutorial}
                                            for g in __import__("games").GAMES.values()]})

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

    async def hub_proxy(request):
        """GET/POST to the hub, from this origin: the camera picture and depth (with their frame
        number), the point cloud, the PLY export, status and the hub's controls."""
        import aiohttp
        path = request.match_info["path"]
        if not (path.startswith(("frame/", "api/")) or path in ("cloud.bin", "cloud.ply", "depth-scale.png")):
            raise web.HTTPNotFound()
        url = f"{HUB}/{path}" + (f"?{request.query_string}" if request.query_string else "")
        data = await request.read() if request.method == "POST" else None
        try:
            async with svc.http().request(request.method, url, data=data, headers={
                    "Content-Type": request.headers.get("Content-Type", "application/json")}) as r:
                body = await r.read()
                headers = {k: v for k, v in r.headers.items() if k in ("X-Seq", "Content-Disposition")}
                headers["Cache-Control"] = "no-store"
                return web.Response(body=body, status=r.status, headers=headers,
                                    content_type=r.content_type)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            return web.json_response({"error": f"Kinect hub: {err}"}, status=503)

    async def demo(request):
        import demos
        out = demos.frames(request.match_info["key"], float(request.query.get("height", "1.75") or 1.75))
        if out is None:
            raise web.HTTPNotFound(text="No demonstration for that")
        return web.json_response(out, headers={"Cache-Control": "max-age=3600"})

    async def pose_demo(_request):
        import demos
        import games as gameslib
        return web.json_response([{"name": p["name"], "frames": [[[round(float(v), 3) for v in j] for j in
                                                                  demos.pose_figure(p["a"])]]}
                                  for p in gameslib.POSES])

    async def insight(request):
        """A person's movement summaries, tracking quality, games and best scores."""
        uid = int(request.query.get("user", "0") or 0)
        return web.json_response({"movement": svc.store.movement(uid), "quality": svc.store.quality(uid),
                                  "games": svc.store.games(uid)[:20], "best": svc.store.best_games(uid)})

    async def forget(request):
        b = await body(request)
        if b.get("session"):
            svc.store.delete_session(int(b["session"]))
        elif b.get("all"):
            svc.store.delete_history(None)
        elif b.get("user"):
            svc.store.delete_history(int(b["user"]))
        else:
            raise web.HTTPBadRequest(text="session, user or all")
        return web.json_response({"ok": True})

    # -- 3D scanning (scan.py, scan_worker.py)

    def scan_colours():
        sys.path.insert(0, str(HERE.parents[1] / "scripts"))
        import adaptive_tokens
        t = adaptive_tokens.load()
        bgr = lambda name: tuple(int(t.hex(name)[i:i + 2], 16) for i in (5, 3, 1))   # noqa: E731
        return {"subject": bgr("accent"), "edge": bgr("white")}

    async def scan_job(request):
        sc = svc.scanner
        if request.method == "GET":
            return web.json_response(sc.job.to_dict() if sc.job else None)
        if request.method == "DELETE":
            await asyncio.get_running_loop().run_in_executor(None, sc.discard)
            return web.json_response({"ok": True})
        b = await body(request)
        if request.method == "PATCH":
            try:
                return web.json_response(sc.update(b.get("segment") or {}).to_dict())
            except LookupError as err:
                raise web.HTTPNotFound(text=str(err))
        # POST: a new scan. A workout or game under way must be paused first, with consent.
        now = time.time()
        with svc.lock:
            live = svc.engine.live()
            what = svc.engine.activity()
        if live and not b.get("pause_activity"):
            return web.json_response({"needs_pause": True, "activity": what,
                                      "say": "A workout or game is running. Pause it to scan?"}, status=409)
        if live:
            with svc.lock:
                svc.engine.workout.pause(now)
                svc.engine.stop_game(now)
        try:
            job = await asyncio.get_running_loop().run_in_executor(None, sc.create, b.get("kind"), b.get("segment"))
        except ValueError as err:
            raise web.HTTPBadRequest(text=str(err))
        return web.json_response(job.to_dict())

    async def scan_preview(_request):
        sc = svc.scanner
        if sc.job is None:
            raise web.HTTPNotFound(text="No scan under way")
        got = await asyncio.get_running_loop().run_in_executor(None, svc.depth_now)
        if got is None:
            return web.json_response({"waiting": "Waiting for the Kinect…"})
        depth, mode, intr = got
        if mode != "ir":
            return web.json_response({"waiting": "Switching the Kinect to infrared depth for scanning…"})
        import base64
        import scan as scanlib
        jpg, stats = await asyncio.get_running_loop().run_in_executor(
            None, scanlib.preview, depth, intr, sc.job.kind, sc.job.segment, scan_colours())
        return web.json_response({"jpg": base64.b64encode(jpg).decode() if jpg else None, "stats": stats})

    async def scan_run(request):
        b = await body(request)
        what = b.get("what")
        if what not in ("background", "capture", "reconstruct"):
            raise web.HTTPBadRequest(text="what: background, capture or reconstruct")
        try:
            extra = {k: b[k] for k in ("seconds", "fps") if k in b}
            job = svc.scanner.run(what, **extra)
        except (LookupError, RuntimeError) as err:
            raise web.HTTPConflict(text=str(err))
        return web.json_response(job.to_dict())

    async def scan_cancel(_request):
        await asyncio.get_running_loop().run_in_executor(None, svc.scanner.cancel)
        return web.json_response({"ok": True})

    async def scan_geometry(request):
        try:
            path = svc.scanner.result_dir(request.match_info["id"]) / "geometry.bin"
        except LookupError as err:
            raise web.HTTPNotFound(text=str(err))
        return web.FileResponse(path, headers={"Cache-Control": "no-store"})

    async def scan_export(request):
        try:
            name, path = await asyncio.get_running_loop().run_in_executor(
                None, svc.scanner.export, request.match_info["id"], request.query.get("format", "stl"),
                request.query.get("units", "mm"), request.query.get("what", "mesh"))
        except LookupError as err:
            raise web.HTTPNotFound(text=str(err))
        except ValueError as err:
            raise web.HTTPBadRequest(text=str(err))
        return web.FileResponse(path, headers={"Content-Disposition": f'attachment; filename="{name}"'})

    async def scan_save(request):
        b = await body(request)
        try:
            dest = await asyncio.get_running_loop().run_in_executor(
                None, svc.scanner.save, request.match_info["id"], b.get("name"), svc.store)
        except LookupError as err:
            raise web.HTTPNotFound(text=str(err))
        return web.json_response({"ok": True, "path": str(dest)})

    async def scans(request):
        if request.method == "DELETE":
            sid = int(request.match_info["sid"])
            row = next((r for r in svc.store.scans() if r["id"] == sid), None)
            if row and request.query.get("files") == "1":
                import scan as scanlib
                path = Path(row["path"]).resolve()
                if scanlib.SCANS.resolve() in path.parents:
                    shutil.rmtree(path, ignore_errors=True)
            svc.store.delete_scan(sid)
            return web.json_response({"ok": True})
        return web.json_response(svc.store.scans())

    async def game(request):
        b = await body(request)
        now = time.time()
        with svc.lock:
            if b.get("action") == "start":
                key = b.get("game")
                import games as gameslib
                if key not in gameslib.GAMES:
                    raise web.HTTPBadRequest(text="game: walls, pose or race")
                kw = {"steer": b["steer"]} if key == "race" and b.get("steer") in ("wheel", "lean") else {}
                svc.engine.workout.finish(now)
                svc.engine.start_game(key, now, b.get("seed"), **kw)
            elif b.get("action") == "stop":
                svc.engine.stop_game(now)
            else:
                raise web.HTTPBadRequest(text="action: start or stop")
        return web.json_response({"ok": True})

    async def calibration_api(request):
        if request.method == "POST":
            b = await body(request)
            if "tilt_by" in b:
                status = await asyncio.get_running_loop().run_in_executor(None, svc._hub_status)
                now_tilt = (status or {}).get("tilt") or 0.0
                target = max(-27.0, min(27.0, float(now_tilt) + float(b["tilt_by"])))
                await asyncio.get_running_loop().run_in_executor(None, svc._hub_post, "tilt", target)
                return web.json_response({"ok": True, "tilt": target})
            raise web.HTTPBadRequest(text="tilt_by expected")
        return web.json_response(svc.snapshot.get("space") or {"error": "The floor is not in view yet."})

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
        if "space_m" in b:
            v = b["space_m"]
            svc.cfg["space_m"] = None if v in (None, "", 0) else max(1.0, min(6.0, float(v)))
            svc.engine.cfg["space_m"] = svc.cfg["space_m"]
            svc.engine.space_key = None
        save_config(svc.cfg)
        return web.json_response({"ok": True})

    async def config(_request):
        return web.json_response({k: svc.cfg.get(k) for k in ("zones", "voice", "room_always",
                                                              "sit_minutes", "webhook", "space_m")})

    async def app_page(_request):
        return web.FileResponse(STATIC / "app.html", headers={"Cache-Control": "no-cache"})

    def legacy(section):
        async def handler(request):
            game = request.query.get("game")
            raise web.HTTPFound(f"/app#/{section}" + (f"/{game}" if game else ""))
        return handler

    app = web.Application()
    app.router.add_get("/", lambda _r: web.HTTPFound("/app"))
    app.router.add_get("/app", app_page)
    for name, section in (("fitness", "fitness"), ("arcade", "games"), ("room", "room"),
                          ("studio", "camera"), ("scan", "scan")):
        app.router.add_get(f"/{name}", legacy(section))
    app.router.add_route("*", "/hub/{path:.*}", hub_proxy)
    app.router.add_get("/api/demo/{key}", demo)
    app.router.add_get("/api/poses", pose_demo)
    app.router.add_get("/api/insight", insight)
    app.router.add_route("*", "/api/scan", scan_job)
    app.router.add_get("/api/scan/preview", scan_preview)
    app.router.add_post("/api/scan/run", scan_run)
    app.router.add_post("/api/scan/cancel", scan_cancel)
    app.router.add_get("/api/scan/{id}/geometry.bin", scan_geometry)
    app.router.add_get("/api/scan/{id}/export", scan_export)
    app.router.add_post("/api/scan/{id}/save", scan_save)
    app.router.add_get("/api/scans", scans)
    app.router.add_delete("/api/scans/{sid}", scans)
    app.router.add_post("/api/forget", forget)
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
    app.router.add_post("/api/game", game)
    app.router.add_route("*", "/api/calibration", calibration_api)
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
    if getattr(svc, "_http", None) is not None:
        await svc._http.close()
    await runner.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--demo", action="store_true", help="synthetic people instead of the Kinect")
    parser.add_argument("--db", help="history file (default ~/.local/share/adaptive-desktop/fitness.db)")
    args = parser.parse_args()
    # The demo is the app with synthetic people: it uses neither your settings nor your history.
    cfg = {"voice": False, "space_m": None} if args.demo else load_config()
    svc = Service(cfg, storelib.Store(args.db), demo=args.demo)
    worker = threading.Thread(target=svc.run, name="hub-reader", daemon=True)
    worker.start()
    threading.Thread(target=svc.watchdog, name="watchdog", daemon=True).start()
    import signal
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: svc.stop.set())
    try:
        asyncio.run(serve(svc, args.port))
    finally:
        svc.stop.set()
        svc.scanner.discard()                 # unsaved scans do not outlive the service
        if svc.pad is not None:
            svc.pad.close()
        worker.join(timeout=3)
    return 0


if __name__ == "__main__":
    sys.exit(main())
