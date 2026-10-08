"""Private graphical desktops, owned by paired phones.

All X operations require a session object. There is deliberately no default
DISPLAY in this module. Laptop services remain on the existing host routes.
"""
import asyncio
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import sys
import time
import uuid

from aiohttp import web, WSMsgType
import app_workspace
import control_profiles
import desktop
import inputs
import machine
import screen

FRAMEBUFFER = (4096, 4096)
REQUIRED = ("Xvfb", "xfwm4", "dbus-daemon", "xdotool", "xprop", "xauth")
# Left by whatever started the daemon, and meaningful only on the laptop.
INHERITED = ("VSCODE_", "ELECTRON_", "CHROME_DESKTOP", "GIO_LAUNCHED_DESKTOP_FILE", "BAMF_DESKTOP_FILE_HINT",
             "GNOME_TERMINAL_", "GNOME_KEYRING_", "TERM_PROGRAM", "XDG_SESSION_ID", "XDG_SEAT", "XDG_VTNR")
# The Debian/Ubuntu package that provides each of REQUIRED.
PACKAGES = {"Xvfb": "xvfb", "xfwm4": "xfwm4", "dbus-daemon": "dbus", "xdotool": "xdotool", "xprop": "x11-utils", "xauth": "xauth"}
# What a launch showed about an app, kept per app rather than per phone.
COMPATIBILITY = {"running": "works", "no-window": "no-window", "failed": "failed"}


def record_compatibility(path, app_id, state):
    try:
        data = json.loads(Path(path).read_text())
    except (FileNotFoundError, ValueError):
        data = {}
    data[app_id] = {"result": COMPATIBILITY[state], "checked": int(time.time())}
    control_profiles.atomic_json(path, data)


@dataclass(frozen=True)
class ExecutionTarget:
    kind: str
    session: str = ""

    def __post_init__(self):
        if self.kind not in ("laptop", "phone") or (self.kind == "phone" and not self.session):
            raise ValueError("an explicit execution target is required")


def viewport(value):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("viewport must be [width, height]")
    return tuple(max(320, min(3840, int(n))) for n in value)


async def stop_process(proc):
    if proc is None or proc.returncode is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        await asyncio.wait_for(proc.wait(), 3)
    except asyncio.TimeoutError:
        os.killpg(proc.pid, signal.SIGKILL)
        await proc.wait()
    except ProcessLookupError:
        pass


class MobileSession:
    def __init__(self, root, owner):
        self.id = uuid.uuid4().hex
        self.owner = owner
        self.root = Path(root) / hashlib.sha256(owner.encode()).hexdigest()
        self.runtime = self.root / "runtime"
        self.env = None
        self.input = None
        self.processes = []
        self.apps = {}
        self.windows = []
        self.selected = 0
        self.split = 0
        self.selected_app = ""
        self.size = (800, 1280)
        self.canvas = self.size
        self.lock = asyncio.Lock()
        self.xserver = self.bus = self.wm = None
        self.sink_module = None
        self.sink = "adaptive_phone_" + self.id
        self.audio = False
        self.media = None
        self.sockets = set()
        self.state = "starting"
        self.seen = time.monotonic()
        self.last_fit = {}
        self.report = None

    async def run(self, *args):
        if self.env is None:
            raise ValueError("the phone session has no display")
        return await asyncio.to_thread(machine._run, *args, env=self.env)

    async def start(self):
        missing = [name for name in REQUIRED if not shutil.which(name)]
        if missing:
            raise ValueError("Install phone-session dependencies: " + ", ".join(missing))
        for name in ("runtime", "config", "cache", "data", "state", "profiles"):
            path = self.root / name
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.chmod(0o700)
        auth = self.runtime / "Xauthority"
        auth.touch(mode=0o600, exist_ok=True)
        # A fresh, internal cookie. Never read the operator's X authority.
        cookie = secrets.token_hex(16)
        ok, _ = await asyncio.to_thread(machine._run, "xauth", "-f", str(auth), "add", ":0", ".", cookie)
        if not ok:
            raise ValueError("could not prepare the private display")
        # -displayfd chooses a free display atomically; Xvfb authenticates with
        # the cookie regardless of the authority record's display number.
        read_fd, write_fd = os.pipe()
        try:
            self.xserver = await asyncio.create_subprocess_exec(
                "Xvfb", "-displayfd", str(write_fd), "-screen", "0", "4096x4096x24", "-nolisten", "tcp", "-auth", str(auth),
                pass_fds=(write_fd,), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
            os.close(write_fd)
            write_fd = -1
            def read_display():
                import select
                if not select.select([read_fd], [], [], 8)[0]:
                    raise ValueError("private display did not start")
                return os.read(read_fd, 32).decode().strip()
            number = await asyncio.to_thread(read_display)
        finally:
            os.close(read_fd)
            if write_fd >= 0:
                os.close(write_fd)
        if not number.isdigit():
            raise ValueError("private display failed; retry session creation")
        display = ":" + number
        await asyncio.to_thread(machine._run, "xauth", "-f", str(auth), "add", display, ".", cookie)
        self.env = dict(os.environ)
        for key in ("WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "SESSION_MANAGER", "DESKTOP_STARTUP_ID", "XDG_ACTIVATION_TOKEN"):
            self.env.pop(key, None)
        # What the daemon's own launcher left behind would hand an app back to
        # the laptop: VSCODE_IPC_HOOK opens files in the laptop's editor.
        for key in list(self.env):
            if key.startswith(INHERITED):
                del self.env[key]
        self.env.update(DISPLAY=display, XAUTHORITY=str(auth), XDG_RUNTIME_DIR=str(self.runtime),
                        XDG_CONFIG_HOME=str(self.root / "config"), XDG_CACHE_HOME=str(self.root / "cache"),
                        XDG_DATA_HOME=str(self.root / "data"), XDG_STATE_HOME=str(self.root / "state"),
                        ADAPTIVE_MOBILE_ROOT=str(self.root), XDG_SESSION_TYPE="x11", XDG_CURRENT_DESKTOP="XFCE",
                        GDK_BACKEND="x11", QT_QPA_PLATFORM="xcb", GTK_USE_PORTAL="0")
        # Retain installed per-user desktop entries; never copy their profiles.
        self.env["XDG_DATA_DIRS"] = str(Path.home() / ".local/share") + ":" + os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share")
        self.bus = await asyncio.create_subprocess_exec("dbus-daemon", "--session", "--nofork", "--print-address=1",
            env=self.env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
        address = (await asyncio.wait_for(self.bus.stdout.readline(), 5)).decode().strip()
        if not address:
            raise ValueError("private session bus failed")
        self.env["DBUS_SESSION_BUS_ADDRESS"] = address
        self.wm = await asyncio.create_subprocess_exec("xfwm4", "--compositor=off", env=self.env,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
        self.input = inputs.Input(self.env)
        if not await self.input.start():
            raise ValueError("private display input is unavailable")
        for _ in range(30):
            ok, out = await self.run("xprop", "-root", "_NET_SUPPORTING_WM_CHECK")
            if ok and "window id" in out:
                break
            await asyncio.sleep(.1)
        else:
            raise ValueError("private window manager did not start")
        if shutil.which("pactl"):
            ok, module = await asyncio.to_thread(machine._run, "pactl", "load-module", "module-null-sink", "sink_name=" + self.sink)
            if ok and module.isdigit():
                self.sink_module = module
                self.audio = True
        if self.audio:
            self.env["PULSE_SERVER"] = os.environ.get("PULSE_SERVER", "unix:/run/user/" + str(os.getuid()) + "/pulse/native")
            self.env["PULSE_SINK"] = self.sink
            self.env["PULSE_SOURCE"] = self.sink + ".monitor"
        else:
            # No accidental playback on the physical default sink.
            self.env["PULSE_SERVER"] = "unix:" + str(self.runtime / "audio-unavailable")
        self.state = "ready"

    def alive(self):
        return self.state == "ready" and all(p is not None and p.returncode is None for p in (self.xserver, self.bus, self.wm))

    def public(self):
        alive = self.alive()
        return {"id": self.id, "state": "ready" if alive else "failed", "viewport": list(self.size), "canvas": list(self.canvas),
                "selected_window": self.selected, "split_window": self.split, "selected_app": self.selected_app, "audio": self.audio,
                "apps": list(self.apps.values()), "windows": self.windows,
                "error": "" if alive else "Private session stopped. End this session and create a new one."}

    async def refresh(self, catalog):
        if not self.alive():
            raise ValueError("private session failed; input will not be sent to the laptop")
        self.windows = await asyncio.to_thread(machine.windows, self.env)
        for window in self.windows:
            old = next((a["app_id"] for a in self.apps.values() if window["id"] in a.get("windows", [])), "")
            candidates = app_workspace.matches(window, catalog, {})
            by_pid = [a["app_id"] for a in self.apps.values() if window["pid"] in a.get("pids", [])]
            window["app_id"] = old or (by_pid[0] if len(by_pid) == 1 else candidates[0] if len(candidates) == 1 else "")
        for window in self.windows:
            if window["parent"]:
                parent = next((w for w in self.windows if w["id"] == window["parent"]), None)
                if parent:
                    window["app_id"] = parent["app_id"]
        exited = {p.pid: p.returncode for p in self.processes if p.returncode is not None}
        for app in self.apps.values():
            app["windows"] = [w["id"] for w in self.windows if w["app_id"] == app["app_id"]]
            # Every launch of it ended in an error before showing a window.
            failed = app["pids"] and all(exited.get(pid) not in (None, 0) for pid in app["pids"])
            app["state"] = "running" if app["windows"] else "failed" if failed else "starting" if time.time() - app["started"] < 15 else "no-window"
            app["message"] = {"running": "", "starting": "Waiting for an independent window",
                              "failed": "This app could not start in the phone session. Nothing was opened on the laptop.",
                              "no-window": "No independent window appeared. Retry or select an unassigned window; this app may require a launch adapter."}[app["state"]]
            if self.report and app["state"] != "starting" and app.get("reported") != app["state"]:
                app["reported"] = app["state"]
                self.report(app["app_id"], app["state"])
        if self.selected_app and not any(w["id"] == self.selected for w in self.windows):
            remaining = [w for w in self.windows if w["app_id"] == self.selected_app]
            self.selected = remaining[0]["id"] if remaining else 0
        if self.selected:
            await self.fit()
        return self.public()

    async def fit(self):
        if self.split and not any(w["id"] == self.split for w in self.windows):
            self.split = 0
        targets = [w for w in self.windows if w["id"] in (self.selected, self.split) or w["app_id"] == self.selected_app and w["parent"]]
        self.canvas = self.size
        for w in targets:
            wid = str(w["id"])
            width = self.size[0] // 2 if self.split else self.size[0]
            x = width + 4 if w["id"] == self.split else 4
            geometry = (x, 28, width - 12, self.size[1] - 40)
            if self.last_fit.get(wid) != geometry or w["maximized"]:
                await self.run(sys.executable, str(Path(__file__).with_name("mobile_window.py")), wid, *(str(v) for v in geometry))
                self.last_fit[wid] = geometry
            ok, geom = await self.run("xdotool", "getwindowgeometry", "--shell", wid)
            if ok:
                values = dict(re.findall(r"^(X|Y|WIDTH|HEIGHT)=(-?\d+)$", geom, re.M))
                right = max(0, int(values.get("X", 0))) + int(values.get("WIDTH", 0)) + 8
                bottom = max(0, int(values.get("Y", 0))) + int(values.get("HEIGHT", 0)) + 8
                self.canvas = (min(4096, max(self.canvas[0], right)), min(4096, max(self.canvas[1], bottom)))

    async def spawn(self, app_id, name, files=()):
        """Start one catalog app on this display through the launch helper."""
        process = await asyncio.create_subprocess_exec(sys.executable, str(Path(__file__).with_name("mobile_launch.py")), app_id, *files,
            env=self.env, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
        self.processes.append(process)
        instance = self.apps.setdefault(app_id, {"app_id": app_id, "name": name, "windows": [], "pids": []})
        instance.update(started=time.time(), state="starting", message="Waiting for its phone window")
        instance.pop("reported", None)
        instance["pids"].append(process.pid)
        return instance

    async def focus(self, wid=None):
        if not self.alive():
            raise ValueError("the phone session is unavailable")
        selected = wid or self.selected
        target = next((w for w in self.windows if w["id"] == selected), None)
        if target is None:
            raise ValueError("select a running phone application")
        if wid:
            self.selected = selected
            self.selected_app = target["app_id"]
            await self.fit()
        # The topmost related dialog must receive input rather than its parent.
        dialog = next((w for w in self.windows if w["parent"] and w["app_id"] == target["app_id"]), target)
        ok, _ = await self.run("xdotool", "windowactivate", "--sync", str(dialog["id"]))
        if not ok:
            raise ValueError("the phone window could not be focused")

    async def close(self):
        self.state = "ending"
        for ws in list(self.sockets):
            await ws.close()
        if self.media:
            await self.media.close_all()
        if self.input:
            await self.input.stop()
        for proc in reversed(self.processes):
            await stop_process(proc)
        for proc in (self.wm, self.bus, self.xserver):
            await stop_process(proc)
        if self.sink_module:
            await asyncio.to_thread(machine._run, "pactl", "unload-module", self.sink_module)
        self.state = "ended"


class MobileDesktop:
    def __init__(self, link):
        self.link = link
        self.sessions = {}
        self.creation = asyncio.Lock()
        self.runs = {}
        self.tasks = {}

    @staticmethod
    def capabilities():
        missing = [name for name in REQUIRED if not shutil.which(name)]
        return {"version": 1, "available": not missing, "missing": missing}

    def compatibility_path(self):
        return self.link.link_dir / "mobile" / "compatibility.json"

    def compatibility(self):
        try:
            return json.loads(self.compatibility_path().read_text())
        except (FileNotFoundError, ValueError):
            return {}

    def record(self, app_id, state):
        record_compatibility(self.compatibility_path(), app_id, state)

    def routes(self, router):
        guard = self.link.workspace.guarded
        for path, get, post in (("sessions", self.get_sessions, self.change_session), ("apps", self.get_apps, self.change_app),
                                ("layout", self.get_layout, self.save_layout), ("runs", self.get_runs, self.change_run)):
            router.add_get("/v1/mobile/" + path, guard(get))
            router.add_post("/v1/mobile/" + path, guard(post))
        router.add_get("/v1/mobile/screen", self.screen)
        router.add_get("/v1/mobile/input", self.input_socket)
        router.add_post("/v1/mobile/rtc", guard(self.rtc))
        router.add_post("/v1/mobile/rtc/close", guard(self.rtc_close))

    def permit(self, name="allow_input"):
        self.link.workspace.permit(name)

    def owner(self, request):
        return self.link.workspace.owner(request)

    def session(self, ident, owner):
        s = self.sessions.get(ident)
        if s is None:
            raise ValueError("phone session not found; reconnect from Home")
        if s.owner != owner:
            raise PermissionError("this session belongs to another phone")
        if not any(p["fingerprint"] == owner for p in self.link.phones):
            raise PermissionError("phone is no longer paired")
        s.seen = time.monotonic()
        return s

    async def catalog(self):
        # Catalog metadata only: do not inspect or focus host windows.
        return await asyncio.to_thread(desktop.applications, True)

    async def get_sessions(self, request):
        owner = self.owner(request)
        catalog = await self.catalog()
        result = []
        for s in self.sessions.values():
            if s.owner == owner:
                s.seen = time.monotonic()
                result.append(await s.refresh(catalog) if s.alive() else s.public())
        return {"ok": True, "sessions": result, "capability": self.capabilities()}

    async def change_session(self, request):
        self.permit()
        body = await request.json()
        owner = self.owner(request)
        op = body.get("operation", "open")
        if op == "open":
            async with self.creation:
                s = next((s for s in self.sessions.values() if s.owner == owner), None)
                if s is None:
                    if len(self.sessions) >= 4:
                        raise ValueError("four phone sessions are already running")
                    s = MobileSession(self.link.link_dir / "mobile", owner)
                    s.report = self.record
                    try:
                        await s.start()
                    except BaseException:
                        await s.close()
                        raise
                    self.sessions[s.id] = s
                if "viewport" in body:
                    s.size = viewport(body["viewport"])
                return {"ok": True, "session": await s.refresh(await self.catalog())}
        s = self.session(body.get("session"), owner)
        async with s.lock:
            if op == "resize":
                s.size = viewport(body.get("viewport"))
                await s.refresh(await self.catalog())
            elif op in ("end", "force-end"):
                await self.cancel_owner(owner)
                if op == "force-end" and body.get("confirm") is not True:
                    return {"ok": False, "confirm": True, "error": "Force ending loses unsaved work in this phone session"}
                if op == "end":
                    await s.refresh(await self.catalog())
                    for w in list(s.windows):
                        await s.run("xdotool", "windowactivate", "--sync", str(w["id"]), "key", "--clearmodifiers", "alt+F4")
                    await asyncio.sleep(.25)
                    await s.refresh(await self.catalog())
                    if s.windows:
                        await s.focus(s.windows[0]["id"])
                        return {"ok": False, "pending": True, "error": "Applications are still open. Resolve save dialogs, then end the session again.", "session": s.public()}
                await s.close()
                self.sessions.pop(s.id, None)
            else:
                raise ValueError("unknown session operation")
        return {"ok": True, "session": s.public()}

    async def get_apps(self, request):
        catalog = await self.catalog()
        s = self.session(request.query.get("session"), self.owner(request)) if request.query.get("session") else None
        if s:
            await s.refresh(catalog)
        known = self.compatibility()
        apps = [dict(app, compatibility=known[app["id"]]["result"]) if app["id"] in known else app for app in catalog]
        return {"ok": True, "apps": apps, "session": s.public() if s else None}

    async def launch(self, s, app_id, new=False, files=()):
        self.permit()
        catalog = await self.catalog()
        app = next((a for a in catalog if a["id"] == app_id), None)
        if app is None:
            raise ValueError("application is not in the installed catalog")
        if any(word in app_id.lower() for word in ("gnome-control-center", "unity-control-center")):
            return {"ok": True, "native": "control-center"}
        await s.refresh(catalog)
        existing = [w for w in s.windows if w["app_id"] == app_id and not w["parent"]]
        if existing and not new and not files:
            if len(existing) > 1:
                return {"ok": True, "choose_window": existing, "session": s.public()}
            await s.focus(existing[0]["id"])
            return {"ok": True, "session": s.public()}
        instance = await s.spawn(app_id, app["name"], files)
        s.selected_app, s.selected = app_id, 0
        before = {w["id"] for w in s.windows}
        for _ in range(12):
            await asyncio.sleep(.25)
            await s.refresh(catalog)
            found = [w for w in s.windows if w["app_id"] == app_id and w["id"] not in before]
            if found:
                await s.focus(found[0]["id"])
                break
        self.link.audit.write(s.owner, "mobile-launch", f"{app_id} session={s.id} {instance['state']}")
        return {"ok": True, "session": s.public(), "status": instance["state"]}

    async def change_app(self, request):
        self.permit()
        body = await request.json()
        s = self.session(body.get("session"), self.owner(request))
        async with s.lock:
            op = body.get("operation", "launch")
            if op == "open-file":
                self.permit("allow_files")
                path = desktop.resolve(body.get("path", ""))
                if not path.exists():
                    raise ValueError("file is no longer available")
                if await asyncio.to_thread(desktop.opens_as_program, str(path)):
                    self.permit("allow_exec")
                def default_app():
                    from gi.repository import Gio
                    kind = Gio.File.new_for_path(str(path)).query_info("standard::content-type", Gio.FileQueryInfoFlags.NONE, None).get_content_type()
                    app = Gio.AppInfo.get_default_for_type(kind, False)
                    return app.get_id() if app else ""
                app_id = await asyncio.to_thread(default_app)
                if not app_id:
                    raise ValueError("choose an application from the drawer and open this file from its file picker")
                return await self.launch(s, app_id, files=[str(path)])
            if op == "launch":
                return await self.launch(s, body.get("app_id"), body.get("new_window") is True)
            await s.refresh(await self.catalog())
            wid = int(body.get("window", 0))
            w = next((w for w in s.windows if w["id"] == wid), None)
            if w is None:
                raise ValueError("window is not in this phone session")
            if op == "split":
                s.split = 0 if s.split == wid else wid
                s.last_fit.clear()
                await s.fit()
            elif op == "activate":
                if wid == s.split:
                    s.split = s.selected
                await s.focus(wid)
            elif op == "associate":
                app = next((a for a in await self.catalog() if a["id"] == body.get("app_id")), None)
                if app is None:
                    raise ValueError("unknown application")
                s.apps.setdefault(app["id"], {"app_id": app["id"], "name": app["name"], "pids": [], "started": time.time(), "windows": []})["windows"].append(wid)
                w["app_id"] = app["id"]
                await s.focus(wid)
            elif op == "close":
                await s.focus(wid)
                await s.run("xdotool", "key", "--clearmodifiers", "alt+F4")
            elif op == "force-quit":
                if body.get("confirm") is not True:
                    return {"ok": False, "confirm": True, "error": "Force quit may lose this application's unsaved work"}
                # XKillClient disconnects this private display's client only.
                await s.run("xdotool", "windowkill", str(wid))
            else:
                raise ValueError("unknown app operation")
            return {"ok": True, "session": await s.refresh(await self.catalog())}

    def layout_path(self, owner):
        return self.link.link_dir / "mobile" / hashlib.sha256(owner.encode()).hexdigest() / "shell.json"

    async def get_layout(self, request):
        path = self.layout_path(self.owner(request))
        try:
            layout = json.loads(path.read_text())
        except FileNotFoundError:
            layout = {"schema": 1, "revision": 0, "pins": [], "dock": [], "folders": {}, "recent": []}
        return {"ok": True, "layout": layout}

    async def save_layout(self, request):
        body = await request.json()
        current = (await self.get_layout(request))["layout"]
        if body.get("revision") != current["revision"]:
            return {"ok": False, "conflict": True, "layout": current}
        layout = body.get("layout")
        if not isinstance(layout, dict) or len(json.dumps(layout)) > 65536 or layout.get("schema") != 1:
            raise ValueError("invalid shell layout")
        for key in ("pins", "dock", "recent"):
            entries = layout.get(key, [])
            if not isinstance(entries, list) or len(entries) > 200 or any(not isinstance(v, str) or len(v) > 500 for v in entries):
                raise ValueError("invalid shell app list")
        for key in ("folders", "pinned_folders", "viewports", "drawer"):
            if not isinstance(layout.get(key, {}), dict):
                raise ValueError("invalid shell preferences")
        # Project only shell preferences; no pairing material is persisted here.
        saved = {key: layout.get(key, default) for key, default in (("pins", []), ("dock", []), ("folders", {}), ("recent", []), ("pinned_folders", {}), ("viewports", {}), ("drawer", {}))}
        saved.update(schema=1, revision=current["revision"] + 1)
        control_profiles.atomic_json(self.layout_path(self.owner(request)), saved)
        return {"ok": True, "layout": saved}

    async def reader(self, ws, s, region=None):
        mapping = region or (lambda: (0, 0, *s.canvas))
        held = frozenset()
        try:
            while not ws.closed:
                permitted = self.link._allowed("allow_input") and s.alive() and any(p["fingerprint"] == s.owner for p in self.link.phones)
                if not permitted or s.lock.locked():
                    for event in inputs.release(held):
                        await s.input.send(event)
                    held = frozenset()
                try:
                    msg = await ws.receive(timeout=.5)
                except asyncio.TimeoutError:
                    continue
                if msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR):
                    break
                if msg.type != WSMsgType.TEXT or not permitted or s.lock.locked():
                    continue
                try:
                    event = json.loads(msg.data)
                except ValueError:
                    continue
                async with s.lock:
                    # Pointer coordinates are scoped to the captured private canvas.
                    event = inputs.in_region(event, mapping(), FRAMEBUFFER)
                    events = inputs.pen_as_pointer(event) if isinstance(event, dict) and event.get("t") == "pen" else [event]
                    for event in events:
                        if await s.input.send(event):
                            held = inputs.held_after(held, event)
        finally:
            for event in inputs.release(held):
                await s.input.send(event)
            await self.cancel_owner(s.owner)

    async def socket_session(self, request):
        try:
            s = self.session(request.query.get("session"), self.owner(request))
            if not s.alive():
                raise ValueError("private session is unavailable")
            return s
        except (ValueError, PermissionError) as error:
            raise web.HTTPForbidden(text=str(error))

    async def input_socket(self, request):
        if not self.link._allowed("allow_input"):
            raise web.HTTPForbidden(text="phone input is turned off")
        s = await self.socket_session(request)
        ws = web.WebSocketResponse(heartbeat=10, max_msg_size=65536)
        await ws.prepare(request)
        s.sockets.add(ws)
        self.link._track(ws)
        try:
            region = (0, 0, *s.canvas)
            await self.reader(ws, s, lambda: region)
        finally:
            s.sockets.discard(ws)
        return ws

    async def screen(self, request):
        s = await self.socket_session(request)
        ws = web.WebSocketResponse(heartbeat=10, max_msg_size=65536)
        await ws.prepare(request)
        s.sockets.add(ws)
        self.link._track(ws)
        capture = screen.Capture(FRAMEBUFFER, request.query.get("preset", "medium"), (0, 0, *s.canvas), s.env["DISPLAY"], env=s.env)
        reader = None
        try:
            await asyncio.to_thread(capture.start)
            reader = asyncio.create_task(self.reader(ws, s, lambda: capture.region))
            while not ws.closed and not reader.done() and s.alive():
                capture_size = capture.region[2:]
                if capture_size != s.canvas:
                    await asyncio.to_thread(capture.stop)
                    capture.region = (0, 0, *s.canvas)
                    await asyncio.to_thread(capture.start)
                frame = await asyncio.to_thread(capture.next_frame, 1)
                if frame:
                    await ws.send_bytes(frame)
        finally:
            if reader:
                reader.cancel()
                await asyncio.gather(reader, return_exceptions=True)
            await asyncio.to_thread(capture.stop)
            s.sockets.discard(ws)
            await ws.close()
        return ws

    async def rtc(self, request):
        body = await request.json()
        s = self.session(body.get("session"), self.owner(request))
        if not s.alive():
            raise ValueError("private display unavailable")
        import media
        if s.media is None:
            s.media = media.MediaServer(relay=self.link.relay)
        result = await asyncio.wait_for(s.media.answer(body.get("offer"), FRAMEBUFFER, body.get("preset", "medium"),
            body.get("sound") is not False and s.audio, (0, 0, *s.canvas), display=s.env["DISPLAY"], audio_device=s.sink + ".monitor", env=s.env), 30)
        return {"ok": True, **result}

    async def rtc_close(self, request):
        body = await request.json()
        s = self.session(body.get("session"), self.owner(request))
        return {"ok": bool(s.media and await s.media.close(body.get("id")))}

    async def cancel_owner(self, owner):
        tasks = [t for ident, t in self.tasks.items() if self.runs[ident]["owner"] == owner]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def get_runs(self, request):
        runs = [r for r in self.runs.values() if r["owner"] == self.owner(request)]
        for r in runs:
            r["seen"] = time.monotonic()
        return {"ok": True, "runs": [{k: v for k, v in r.items() if k not in ("owner", "seen")} for r in runs]}

    async def change_run(self, request):
        self.permit()
        body = await request.json()
        owner = self.owner(request)
        if body.get("operation") == "cancel":
            await self.cancel_owner(owner)
            return {"ok": True}
        s = self.session(body.get("session"), owner)
        ident = body.get("request_id", "")
        if not isinstance(ident, str) or not control_profiles.ID.fullmatch(ident):
            raise ValueError("unique request ID required")
        if ident in self.runs:
            if self.runs[ident]["owner"] != owner:
                raise PermissionError("request belongs to another phone")
            return {"ok": True, "run": {k: v for k, v in self.runs[ident].items() if k not in ("owner", "seen")}}
        raw = body.get("steps")
        if not isinstance(raw, list) or not 1 <= len(raw) <= 30:
            raise ValueError("use 1 to 30 steps")
        steps = [control_profiles.binding(v) for v in raw]
        if any(step["scope"] == "app" and step["kind"] in ("keys", "text") for step in steps):
            if body.get("app_id") != s.selected_app or not s.selected:
                raise ValueError("open this application's phone window before testing its controls")
        if any(r["state"] == "running" and r["owner"] == owner for r in self.runs.values()):
            raise ValueError("a control is already running")
        if body.get("hold") and (len(steps) != 1 or steps[0]["kind"] != "keys" or "+" in steps[0]["value"]):
            raise ValueError("hold requires a single key")
        # Laptop actions must be explicitly global, including power confirmations.
        for step in steps:
            if step["kind"] == "action" and step["scope"] != "global":
                raise ValueError("registered laptop actions must explicitly target Global")
            if step["kind"] == "action" and self.link._risk(step["value"], step["args"]) == "destroys" and not body.get("confirm"):
                return {"ok": False, "confirm": True, "error": "Confirm this laptop action"}
        run = {"id": ident, "owner": owner, "state": "running", "step": 0, "total": len(steps), "error": "", "seen": time.monotonic()}
        self.runs[ident] = run
        self.tasks[ident] = asyncio.create_task(self.execute(s, run, steps, body, request["peer"]))
        for old in list(self.runs)[:-200]:
            if self.runs[old]["state"] != "running":
                del self.runs[old]
        return {"ok": True, "run": {k: v for k, v in run.items() if k not in ("owner", "seen")}}

    async def execute(self, s, run, steps, body, peer):
        held = set()
        started = time.monotonic()
        async def monitor():
            while True:
                await asyncio.sleep(.5)
                if time.monotonic() - run["seen"] > 8 or not self.link._allowed("allow_input") or not s.alive():
                    self.tasks[run["id"]].cancel()
                    return
        watcher = asyncio.create_task(monitor())
        async def work():
            async with s.lock:
                for index, step in enumerate(steps):
                    self.permit()
                    self.session(s.id, s.owner)
                    run["step"] = index + 1
                    kind, value = step["kind"], step["value"]
                    if kind in ("keys", "text"):
                        if step["scope"] != "app":
                            raise ValueError("use Desktop Remote for laptop-directed keyboard input")
                        await s.refresh(await self.catalog())
                        await s.focus()
                        event = app_workspace.key_event(value) if kind == "keys" else {"t": "text", "s": value}
                        if body.get("hold"):
                            event = {"t": "keydown", "k": value}
                        if not await s.input.send(event):
                            raise ValueError("phone input failed")
                        held.update(inputs.held_after(frozenset(), event))
                        if body.get("hold"):
                            await asyncio.Event().wait()
                    elif kind == "delay":
                        await asyncio.sleep(float(value))
                    elif kind == "layout":
                        run["layout"] = value
                    elif kind == "launch":
                        launch_type = step["args"].get("type", "app")
                        if launch_type == "app":
                            await self.launch(s, value)
                        elif launch_type == "url":
                            from urllib.parse import urlparse
                            if urlparse(value).scheme not in ("http", "https"):
                                raise ValueError("only HTTP and HTTPS URLs are supported")
                            await s.focus()
                            for event in (app_workspace.key_event("ctrl+l"), {"t": "text", "s": value}, app_workspace.key_event("Return")):
                                await s.input.send(event)
                        else:
                            self.permit("allow_files")
                            path = Path(value).expanduser().resolve()
                            if desktop.opens_as_program(path):
                                self.permit("allow_exec")
                            app_id = step["args"].get("app_id")
                            if not app_id:
                                raise ValueError("choose a phone application to open this file")
                            await self.launch(s, app_id, files=[str(path)])
                    elif kind == "wait-window":
                        for _ in range(120):
                            await s.refresh(await self.catalog())
                            found = [w for w in s.windows if w["app_id"] == value]
                            if found:
                                await s.focus(found[0]["id"])
                                break
                            await asyncio.sleep(.25)
                        else:
                            raise ValueError("target phone window did not appear")
                    elif kind == "command":
                        self.permit("allow_exec")
                        proc = await asyncio.create_subprocess_exec("bash", "-c", value, cwd=str(Path(step["cwd"]).expanduser()), env=s.env if step["scope"] == "app" else None,
                            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
                        try:
                            while proc.returncode is None:
                                self.permit("allow_exec")
                                await asyncio.sleep(.1)
                            if proc.returncode:
                                raise ValueError("command failed with exit code " + str(proc.returncode))
                        finally:
                            await stop_process(proc)
                    elif kind == "action":
                        ok, message, _ = await self.link._do(value, step["args"], peer, body.get("confirm") is True)
                        if not ok:
                            raise ValueError(message or "laptop action failed")
                    elif kind == "volume" and step["scope"] == "global":
                        if not await asyncio.to_thread(desktop.set_volume, value):
                            raise ValueError("laptop volume unavailable")
                    else:
                        raise ValueError("this control needs a private-session adapter; edit its binding")
        try:
            await asyncio.wait_for(work(), 120)
            run["state"] = "completed"
        except asyncio.CancelledError:
            run["state"] = "cancelled"
        except Exception as error:
            run.update(state="failed", error=str(error) or "two-minute execution deadline reached")
        finally:
            watcher.cancel()
            for event in inputs.release(held):
                await s.input.send(event)
            run["duration_ms"] = round((time.monotonic() - started) * 1000)
            self.link.audit.write(peer, "mobile-control", f"{run['id']} session={s.id} step={run['step']} {run['state']} {run['duration_ms']}ms")
            self.tasks.pop(run["id"], None)

    async def watch(self):
        while True:
            await asyncio.sleep(2)
            for s in list(self.sessions.values()):
                if not any(p["fingerprint"] == s.owner for p in self.link.phones):
                    await self.cancel_owner(s.owner)
                    await s.close()
                    self.sessions.pop(s.id, None)
                elif time.monotonic() - s.seen > 15:
                    await self.cancel_owner(s.owner)
                    if s.media:
                        await s.media.close_all()

    async def close(self):
        for s in list(self.sessions.values()):
            await self.cancel_owner(s.owner)
            await s.close()
        self.sessions.clear()
