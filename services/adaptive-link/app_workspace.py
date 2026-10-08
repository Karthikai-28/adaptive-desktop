"""Phone-owned app workspaces and cancellable, target-aware controls."""
import asyncio
import base64
import copy
import json
import os
import time
import uuid
from pathlib import Path

from aiohttp import web
import control_profiles as profiles
import desktop
import inputs
import machine
import phone_display


def adapter(app_id):
    name = app_id.casefold()
    for key, words in (("browser", ("firefox", "chrome", "chromium")), ("files", ("nautilus", "adaptivefiles")),
                       ("editor", ("code.desktop", "gedit", "texteditor")), ("terminal", ("terminal", "kterm")),
                       ("media", ("vlc", "rhythmbox")), ("presenter", ("impress",))):
        if any(word in name for word in words):
            return key
    return "universal"


# Desktop actions that open another window: Firefox and Chrome say new-window,
# VS Code new-empty-window, some older apps NewWindow.
NEW_WINDOW = ("new-window", "new-empty-window", "NewWindow")


def matches(window, apps, associations):
    """Return candidates, never silently choose between equally plausible apps."""
    wm = window.get("app", "").casefold()
    if wm and associations.get(wm) in {a["id"] for a in apps}:
        return [associations[wm]]
    exact = [a["id"] for a in apps if window.get("application_id") and
             window["application_id"] in (a["id"], a["id"].removesuffix(".desktop"))]
    if exact:
        return exact
    exact = [a["id"] for a in apps if wm and a.get("wm_class", "").casefold() == wm]
    if exact:
        return exact
    executable = window.get("executable", "")
    return [a["id"] for a in apps if (wm and Path(a.get("executable", "")).name.casefold() == wm) or
            (executable and a.get("executable") == executable)]


def key_event(value):
    parts = value.split("+")
    aliases = {"control": "ctrl", "super": "super", "shift": "shift", "alt": "alt", "ctrl": "ctrl"}
    if not parts or any(p.lower() not in aliases for p in parts[:-1]):
        raise ValueError("invalid shortcut")
    event = {"t": "key", "k": parts[-1], "m": [aliases[p.lower()] for p in parts[:-1]]}
    if not inputs.translate(event, (1920, 1080)):
        raise ValueError("invalid shortcut")
    return event


class Workspace:
    def __init__(self, link):
        self.link = link
        self.profiles = profiles.Profiles(link.link_dir)
        self.sessions = {}
        self.runs = {}
        self.tasks = {}
        self.control_owner = ""
        self.input_lock = asyncio.Lock()
        self.catalog_lock = asyncio.Lock()
        self.catalog = []
        self.catalog_at = 0
        self.association_path = link.link_dir / "app-associations.json"
        try:
            self.associations = json.loads(self.association_path.read_text())
        except (OSError, ValueError):
            self.associations = {}

    def routes(self, router):
        router.add_get("/v1/apps/icon", self.icon)
        for path, get, post in (("app-sessions", self.get_sessions, self.change_session),
                                ("control-profiles", self.get_profiles, self.change_profile),
                                ("control-runs", self.get_runs, self.change_run)):
            router.add_get("/v1/" + path, self.guarded(get))
            router.add_post("/v1/" + path, self.guarded(post))

    def guarded(self, handler):
        async def wrapped(request):
            try:
                return web.json_response(await handler(request))
            except (ValueError, KeyError, TypeError) as error:
                return web.json_response({"ok": False, "error": str(error)}, status=400)
            except PermissionError as error:
                return web.json_response({"ok": False, "error": str(error)}, status=403)
            except OSError:
                return web.json_response({"ok": False, "error": "could not save or access workspace data"}, status=500)
        return wrapped

    @staticmethod
    def owner(request):
        return request["phone"]["fingerprint"]

    def permit(self, name):
        if not self.link._allowed(name):
            raise PermissionError("this phone is not allowed to " + name.removeprefix("allow_"))

    async def apps(self):
        async with self.catalog_lock:
            if time.monotonic() - self.catalog_at > 10:
                self.catalog = await asyncio.to_thread(desktop.applications, True)
                self.catalog_at = time.monotonic()
        windows = await asyncio.to_thread(machine.windows)
        for window in windows:
            try:
                window["executable"] = os.readlink(f"/proc/{window.get('pid', 0)}/exe")
            except OSError:
                window["executable"] = ""
            candidates = matches(window, self.catalog, self.associations)
            window["app_id"] = candidates[0] if len(candidates) == 1 else ""
            window["candidates"] = candidates
        return [{**a, "adapter": adapter(a["id"]), "windows": [w for w in windows if w["app_id"] == a["id"]],
                 "new_window": any(x in a.get("desktop_actions", []) for x in NEW_WINDOW)}
                for a in self.catalog], windows

    async def icon(self, request):
        if not self.catalog:
            await self.apps()
        app = next((a for a in self.catalog if a["id"] == request.query.get("id")), None)
        if not app:
            raise web.HTTPNotFound()
        def load():
            import gi
            gi.require_version("Gtk", "3.0")
            from gi.repository import Gio, Gtk
            icon = Gio.Icon.new_for_string(app["icon"])
            theme = Gtk.IconTheme.get_default()
            info = theme.lookup_by_gicon(icon, 48, Gtk.IconLookupFlags.FORCE_SIZE) if theme else None
            if info is None:
                return None
            return info.load_icon().save_to_bufferv("png", [], [])[1]
        try:
            data = await asyncio.to_thread(load)
        except Exception:
            data = None
        return web.json_response({"png": base64.b64encode(data).decode() if data else ""})

    def session(self, ident, owner):
        session = self.sessions.get(ident)
        if not session or session["owner"] != owner:
            raise ValueError("workspace is closed or belongs to another phone")
        session["seen"] = time.monotonic()
        return session

    async def refresh(self, session):
        session["checked"] = time.monotonic()
        windows = await asyncio.to_thread(machine.windows)
        window = next((w for w in windows if w["id"] == session["window_id"]), None)
        # Parent relationships, rather than titles, identify modal dialogs.
        children = {session["window_id"]}
        for _ in range(4):
            children.update(w["id"] for w in windows if w.get("parent") in children)
        target = next((w for w in windows if w["id"] in children and w["active"]), window)
        session["closed"] = window is None
        session["target"] = target["id"] if target else 0
        session["title"] = target["title"] if target else "Window closed"
        session["focused"] = bool(target and target["active"])
        region = await asyncio.to_thread(machine.region, session["display"]) if session["display"] else None
        if not region and target:
            region = await asyncio.to_thread(phone_display._geometry, target["id"])
        # ximagesrc cannot crop outside the desktop.
        if region:
            x, y, w, h = region
            sw, sh = self.link.input.screen
            x, y = max(0, x), max(0, y)
            region = (x, y, min(w, sw - x), min(h, sh - y))
            if region[2] <= 0 or region[3] <= 0:
                region = None
        session["region"] = list(region) if region else None
        return self.public(session)

    def public(self, session):
        return {k: copy.deepcopy(v) for k, v in session.items() if k not in ("owner", "seen", "original", "checked")} | {
            "control": self.control_owner == session["owner"]}

    async def get_sessions(self, request):
        owner = self.owner(request)
        ident = request.query.get("id")
        if ident:
            return {"ok": True, "session": await self.refresh(self.session(ident, owner))}
        return {"ok": True, "sessions": [await self.refresh(s) for s in list(self.sessions.values()) if s["owner"] == owner]}

    async def change_session(self, request):
        body = await request.json()
        owner = self.owner(request)
        operation = body.get("operation", "open")
        if operation != "open":
            session = self.session(body.get("id"), owner)
            if operation == "close":
                await self.cancel_owner(owner)
                self.sessions.pop(session["id"], None)
                await asyncio.to_thread(phone_display.release, owner)
                if self.control_owner == owner:
                    self.control_owner = ""
                return {"ok": True}
            self.permit("allow_input")
            if operation == "take-control":
                if self.control_owner and self.control_owner != owner:
                    await self.cancel_owner(self.control_owner)
                self.control_owner = owner
            elif operation == "return":
                original = session.get("original")
                if original:
                    await asyncio.to_thread(phone_display._place, session["window_id"], original, 0, 0, 1, 1, False)
                session["display"] = ""
            elif operation == "resize" and session["display"]:
                ok, name = await asyncio.to_thread(phone_display.extend, owner, body.get("size", "800x1280"))
                if ok:
                    session["display"] = name
                    await asyncio.to_thread(phone_display.bring, owner, str(session["window_id"]))
            else:
                raise ValueError("unknown workspace operation")
            return {"ok": True, "session": await self.refresh(session)}
        self.permit("allow_input")
        apps, windows = await self.apps()
        app = next((a for a in apps if a["id"] == body.get("app_id")), None)
        if app is None:
            raise ValueError("application is not installed")
        chosen = int(body.get("window_id", 0))
        candidates = app["windows"]
        if chosen:
            target = next((w for w in windows if w["id"] == chosen), None)
            if target is None:
                raise ValueError("window no longer exists")
            if body.get("remember") and target["app"]:
                self.associations[target["app"].casefold()] = app["id"]
                profiles.atomic_json(self.association_path, self.associations)
        elif len(candidates) > 1 and not body.get("new_window"):
            return {"ok": False, "choose_window": candidates}
        elif candidates and not body.get("new_window"):
            target = candidates[0]
        else:
            before = {w["id"] for w in windows}
            if body.get("new_window"):
                if not app["new_window"]:
                    raise ValueError("this app does not advertise a new-window action")
                def launch_new():
                    from gi.repository import Gio
                    info = Gio.DesktopAppInfo.new(app["id"])
                    action = next(x for x in app["desktop_actions"] if x in NEW_WINDOW)
                    info.launch_action(action, None)
                    return True
                ok = await asyncio.to_thread(launch_new)
            else:
                ok = await asyncio.to_thread(desktop.launch, app["id"])
            if not ok:
                raise ValueError("the application could not be launched")
            target = None
            for _ in range(24):
                await asyncio.sleep(0.25)
                _, windows = await self.apps()
                candidates = [w for w in windows if w["app_id"] == app["id"] and
                              (not body.get("new_window") or w["id"] not in before)]
                if len(candidates) == 1:
                    target = candidates[0]
                    break
            if target is None:
                return {"ok": False, "error": "Launched; choose its window or try again", "choose_window": windows}
        # Opening another app on this phone ends the previous workspace, but not its app.
        await self.cancel_owner(owner)
        for ident in [i for i, s in self.sessions.items() if s["owner"] == owner]:
            self.sessions.pop(ident)
        original = await asyncio.to_thread(phone_display._geometry, target["id"])
        session = {"id": str(uuid.uuid4()), "owner": owner, "app_id": app["id"], "name": app["name"],
                   "adapter": app["adapter"], "window_id": target["id"], "target": target["id"],
                   "display": "", "original": original, "seen": time.monotonic()}
        if not self.control_owner:
            self.control_owner = owner
        if self.control_owner == owner:
            await asyncio.to_thread(machine.window_action, "show", target["id"])
            if body.get("phone_display", True):
                ok, name = await asyncio.to_thread(phone_display.extend, owner, body.get("size", "800x1280"))
                if ok:
                    moved, _ = await asyncio.to_thread(phone_display.bring, owner, str(target["id"]))
                    if moved:
                        session["display"] = name
        self.sessions[session["id"]] = session
        return {"ok": True, "session": await self.refresh(session)}

    async def region(self, ident, owner, whole=False):
        session = self.session(ident, owner)
        await self.refresh(session)
        if session["closed"]:
            raise ValueError("window closed")
        return None if whole else session["region"]

    async def focus(self, ident, owner, fresh=True):
        """Make sure the selected app (or its dialog) has focus before input.

        Live pointer and key events pass fresh=False: reading every window
        costs one xprop per window, too much for each pointer move, so a check
        under half a second old stands. Control steps always look again.
        """
        self.permit("allow_input")
        if self.control_owner != owner:
            raise PermissionError("another phone owns input; take control first")
        session = self.session(ident, owner)
        if fresh or not session.get("focused") or time.monotonic() - session.get("checked", 0) > 0.5:
            await self.refresh(session)
        if session["closed"]:
            raise ValueError("window closed")
        if not session["focused"]:
            ok, _ = await asyncio.to_thread(machine.window_action, "show", session["target"])
            if not ok:
                raise ValueError("cannot focus the selected app")
            session["focused"] = True
        return session

    async def get_profiles(self, request):
        if self.profiles.problem:
            return {"ok": False, "error": self.profiles.problem}
        return {"ok": True, **self.profiles.snapshot()}

    async def change_profile(self, request):
        body = await request.json()
        if body.get("operation") == "delete":
            return self.profiles.delete(body.get("id"), body.get("revision"))
        return self.profiles.save(body.get("profile"), body.get("revision", 0))

    def run_public(self, run):
        return {k: copy.deepcopy(v) for k, v in run.items() if k not in ("owner", "seen", "steps", "session", "confirm", "held")}

    async def get_runs(self, request):
        owner = self.owner(request)
        found = []
        for run in self.runs.values():
            if run["owner"] == owner and (not request.query.get("id") or request.query["id"] == run["id"]):
                run["seen"] = time.monotonic()
                found.append(self.run_public(run))
        return {"ok": True, "runs": found}

    async def change_run(self, request):
        body = await request.json()
        owner = self.owner(request)
        if body.get("operation") == "cancel":
            run = self.runs.get(body.get("id"))
            if run and run["owner"] != owner:
                raise PermissionError("this run belongs to another phone")
            if run and run["id"] in self.tasks:
                self.tasks[run["id"]].cancel()
            return {"ok": True}
        steps = body.get("steps", [])
        if not isinstance(steps, list) or not 1 <= len(steps) <= 30:
            raise ValueError("use 1 to 30 steps")
        steps = [profiles.binding(step) for step in steps]
        ident = body.get("request_id", "")
        if not isinstance(ident, str) or not profiles.ID.fullmatch(ident):
            raise ValueError("a unique request ID is required")
        if ident in self.runs:
            old = self.runs[ident]
            if old["owner"] != owner:
                raise PermissionError("request ID belongs to another phone")
            return {"ok": True, "run": self.run_public(old)}
        if any(r["state"] == "running" for r in self.runs.values()):
            raise ValueError("a control is already running; wait or stop it first")
        session_id = body.get("session", "")
        if any(s["scope"] == "app" and s["kind"] not in ("delay", "layout") for s in steps):
            await self.focus(session_id, owner)
        for step in steps:
            if step["kind"] == "command":
                self.permit("allow_exec")
            if step["kind"] == "action" and self.link._risk(step["value"], step["args"]) == "destroys" and not body.get("confirm"):
                return {"ok": False, "confirm": True, "error": "Confirm this action before running"}
        if body.get("hold") and (len(steps) != 1 or steps[0]["kind"] != "keys" or "+" in steps[0]["value"]):
            raise ValueError("hold requires one key")
        run = {"id": ident, "owner": owner, "session": session_id, "steps": steps, "step": 0, "total": len(steps),
               "state": "running", "error": "", "seen": time.monotonic(), "started": time.time(),
               "confirm": body.get("confirm") is True, "held": [], "hold": bool(body.get("hold"))}
        self.runs[ident] = run
        self.tasks[ident] = asyncio.create_task(self.execute(run, request["peer"]))
        # Keep a bounded deduplication history. Completed runs never restart automatically.
        for old in list(self.runs)[:-200]:
            if self.runs[old]["state"] != "running":
                del self.runs[old]
        return {"ok": True, "run": self.run_public(run)}

    async def execute(self, run, peer):
        async def heartbeat():
            while True:
                await asyncio.sleep(0.5)
                if time.monotonic() - run["seen"] > 8:
                    self.tasks[run["id"]].cancel()
                    return
                if not any(p["fingerprint"] == run["owner"] for p in self.link.phones):
                    self.tasks[run["id"]].cancel()
                    return
        monitor = asyncio.create_task(heartbeat())
        try:
            async with self.input_lock:
                await asyncio.wait_for(self.steps(run, peer), 120)
            run["state"] = "completed"
        except asyncio.CancelledError:
            run["state"] = "cancelled"
        except asyncio.TimeoutError:
            run["state"], run["error"] = "failed", "two-minute execution deadline reached"
        except Exception as error:
            run["state"], run["error"] = "failed", str(error)
        finally:
            monitor.cancel()
            for event in inputs.release(frozenset(run["held"])):
                await self.link.input.send(event)
            run["duration_ms"] = round((time.time() - run["started"]) * 1000)
            self.link.audit.write(peer, "control-run", f"{run['id']} step={run['step']} {run['state']} {run['duration_ms']}ms")
            self.tasks.pop(run["id"], None)

    async def steps(self, run, peer):
        for index, step in enumerate(run["steps"]):
            run["step"] = index + 1
            kind, value, args = step["kind"], step["value"], step["args"]
            session = None
            if step["scope"] == "app" and kind not in ("delay", "layout"):
                session = await self.focus(run["session"], run["owner"])
            if kind in ("keys", "text", "launch", "wait-window") and self.control_owner and self.control_owner != run["owner"]:
                raise PermissionError("another phone owns input; take control first")
            if kind == "delay":
                await asyncio.sleep(float(value))
            elif kind == "layout":
                run["layout"] = value
            elif kind in ("keys", "text"):
                self.permit("allow_input")
                event = key_event(value) if kind == "keys" else {"t": "text", "s": value}
                if run["hold"]:
                    event = {"t": "keydown", "k": value}
                    if not inputs.translate(event, self.link.input.screen):
                        raise ValueError("invalid hold key")
                if not await self.link.input.send(event):
                    raise ValueError("input was refused")
                if run["hold"]:
                    run["held"] = list(inputs.held_after(frozenset(), event))
                    while True:
                        self.permit("allow_input")
                        if self.control_owner != run["owner"]:
                            raise PermissionError("input ownership changed")
                        await asyncio.sleep(0.1)
            elif kind == "action":
                action = self.link.book.actions().get(value) if hasattr(self.link, "book") else None
                if action is not None and action.switch == "allow_input" and self.control_owner and self.control_owner != run["owner"]:
                    raise PermissionError("another phone owns input; take control first")
                ok, _, _ = await self.link._do(value, args, peer, run["confirm"])
                if not ok:
                    raise ValueError("desktop action failed or was refused")
            elif kind == "launch":
                self.permit("allow_input")
                target_type = args.get("type", "app")
                if target_type == "app":
                    ok = await asyncio.to_thread(desktop.launch, value)
                    run["waiting_app"] = value
                elif target_type in ("file", "folder"):
                    self.permit("allow_files")
                    # The same rule as /v1/open: a file that would run as a program needs allow_exec.
                    if await asyncio.to_thread(desktop.opens_as_program, value):
                        self.permit("allow_exec")
                    ok = await asyncio.to_thread(desktop.open_path, value)
                else:
                    url = desktop.web_address(value)
                    if not url:
                        raise ValueError("use an http or https URL")
                    # Browser navigation stays in the selected browser window.
                    if session and adapter(session["app_id"]) == "browser":
                        for event in (key_event("ctrl+l"), {"t": "text", "s": url}, key_event("Return")):
                            if not await self.link.input.send(event):
                                raise ValueError("browser input failed")
                        ok = True
                    else:
                        ok = await asyncio.to_thread(desktop.open_url, url)
                if not ok:
                    raise ValueError("could not open target")
            elif kind == "wait-window":
                self.permit("allow_input")
                app_id = value or run.get("waiting_app", "")
                for _ in range(40):
                    _, windows = await self.apps()
                    found = [w for w in windows if w["app_id"] == app_id]
                    if len(found) == 1:
                        if session:
                            session["window_id"], session["app_id"] = found[0]["id"], app_id
                        break
                    await asyncio.sleep(0.25)
                else:
                    raise ValueError("target window did not appear or needs a window choice")
            elif kind == "command":
                self.permit("allow_exec")
                cwd = desktop.resolve(step["cwd"])
                if not cwd.is_dir():
                    raise ValueError("working directory does not exist")
                process = await asyncio.create_subprocess_exec("bash", "-lc", value, cwd=str(cwd), start_new_session=True,
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, stdin=asyncio.subprocess.DEVNULL)
                waiting = asyncio.create_task(process.wait())
                try:
                    while process.returncode is None:
                        self.permit("allow_exec")
                        try:
                            await asyncio.wait_for(asyncio.shield(waiting), 0.25)
                        except asyncio.TimeoutError:
                            pass
                    if process.returncode != 0:
                        raise ValueError(f"command exited with status {process.returncode}")
                finally:
                    if process.returncode is None:
                        self.link._kill(process)
                        try:
                            await asyncio.wait_for(process.wait(), 2)
                        except asyncio.TimeoutError:
                            import signal
                            try:
                                os.killpg(process.pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                            await process.wait()
            elif kind == "volume":
                self.permit("allow_input")
                if not await asyncio.to_thread(desktop.set_volume, value):
                    raise ValueError("volume change failed")
            elif kind == "media":
                self.permit("allow_input")
                players = await asyncio.to_thread(desktop.players)
                name = session["app_id"].lower() if session else ""
                player = next((p for p in players if p["id"].split(".")[0].lower() in name), None) if session else next(iter(players), None)
                if not player or not player.get("can_control"):
                    raise ValueError("selected app has no controllable media player")
                capability = {"seek": "can_seek", "next": "can_next", "previous": "can_previous", "play": "can_play", "pause": "can_pause"}.get(value)
                if capability and not player.get(capability):
                    raise ValueError("player does not support this action")
                if not await asyncio.to_thread(desktop.media, value, player["id"], args.get("seconds", 0)):
                    raise ValueError("media action failed")

    async def cancel_owner(self, owner):
        tasks = [self.tasks[i] for i, r in self.runs.items() if r["owner"] == owner and i in self.tasks]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def expire(self):
        while True:
            await asyncio.sleep(2)
            owners = {s["owner"] for s in self.sessions.values() if time.monotonic() - s["seen"] > 12}
            for owner in owners:
                await self.cancel_owner(owner)
                for ident in [i for i, s in self.sessions.items() if s["owner"] == owner]:
                    self.sessions.pop(ident, None)
                await asyncio.to_thread(phone_display.release, owner)
                if self.control_owner == owner:
                    self.control_owner = ""

    async def close(self):
        for owner in {r["owner"] for r in self.runs.values()}:
            await self.cancel_owner(owner)
        self.sessions.clear()
        self.control_owner = ""
