"""Adaptive Link - the server the owner's paired phone talks to.

Listeners, each for one kind of caller:

  the link     TCP, mutual TLS. Only the paired phone can finish a handshake
               (identity.link_context), so nothing below /v1 is reachable by
               anyone else. Not started at all until a phone is paired, and
               stopped when the link is turned off. The phone reaches it
               straight over the local network, or - from elsewhere - through
               a direct tunnel that ends at this same port (rtc.py).
  pairing      TCP, TLS without a client certificate, open only for the
               minutes after the owner asks to pair by code, for one phone.
  control      A Unix socket only this user can open: how the pairing window,
               link-cli and the palette talk to the daemon.

And one thing it reaches out to: the owner's Google account (cloud.py), where
a phone signed in to the same account can find this computer and ask to
connect. Asking is all the account gives; the owner approves here.

What a request may do is decided before any handler runs: the address it
came from (identity.peer_allowed), the certificate it presented (TLS, then
checked again here against the stored fingerprint), and the owner's switches
in config.json. Everything the phone does is written to the audit log.
"""

import asyncio
import json
import os
import signal
import socket
import time
from pathlib import Path

import aiohttp
from aiohttp import WSMsgType, web

import camera
import cloud
import desktop
import identity
import inputs
import screen
import system

VERSION = 1
CONNECT_NOTICE_EVERY_S = 600
# How long the phone has to say it can still reach the computer after a
# change that may have cut it off.
KEEP_S = int(os.environ.get("ADAPTIVE_LINK_KEEP_S", "45"))
EXEC_OUTPUT_CHUNK = 4096
PAIR_ASKS_PER_MINUTE = 60
# How old a request made through the account may be and still be acted on.
SIGNAL_FRESH_S = 120
REQUEST_FRESH_S = 600


def control_socket_path():
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(runtime) / "adaptive-link.sock"


def json_error(status, message):
    return web.json_response({"ok": False, "error": message}, status=status)


async def read_json(request):
    try:
        data = await request.json()
    except (ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


class Link:
    def __init__(self, link_dir=None, state_dir=None):
        self.link_dir = Path(link_dir or identity.LINK_DIR)
        self.state_dir = Path(state_dir or identity.STATE_DIR)
        self.config = identity.load_config(self.link_dir)
        self.key_path, self.cert_path, self.fingerprint = identity.server_identity(self.link_dir)
        self.phone = identity.load_phone(self.link_dir)
        self.audit = desktop.Audit(self.state_dir / "link.log")
        self.notifications = desktop.Notifications()
        self.input = inputs.Input()

        self._link_runner = None
        self._pair_runner = None
        self._control_runner = None
        self._pairing = {"state": "idle"}
        self._pair_reached = {"hellos": 0, "alerts": []}
        self._pair_decided = asyncio.Event()
        self._pair_timer = None
        # The owner's Google account (cloud.Account), once their project is
        # set up; what this computer does there is in restart_cloud().
        self.account = None
        self.cloud_state = "not set up"
        self._cloud_task = None
        self._tunnel = None
        self._signin = {"state": "idle"}
        self._signin_task = None
        self._answered = set()   # direct-connection requests already handled
        self._decided = {}       # requests of the account already answered: phone id -> when it asked
        self._last_notice = 0.0
        self.problem = ""
        self._sessions = 0
        self._children = set()
        # Every open socket to the phone, so that switching the link off or
        # unpairing ends what the phone is doing now, not at its next request.
        self._sockets = set()
        self._undo = None   # a change waiting for the phone to keep it
        self._pair_asks = {}

    # ------------------------------------------------------------ listeners

    @property
    def port(self):
        return int(os.environ.get("ADAPTIVE_LINK_PORT") or self.config["port"])

    @property
    def pairing_port(self):
        return int(os.environ.get("ADAPTIVE_LINK_PAIRING_PORT") or identity.PAIRING_PORT)

    async def start(self):
        await self.input.start()
        await self._start_control()
        await self.restart_link()
        await self.restart_cloud()

    async def stop(self):
        if self._cloud_task is not None:
            self._cloud_task.cancel()
        if self._tunnel is not None:
            await self._tunnel.close()
        if self.account is not None:
            await self.account.close()
        for process in list(self._children):
            self._kill(process)
        await self.input.stop()
        for runner in (self._link_runner, self._pair_runner, self._control_runner):
            if runner is not None:
                await runner.cleanup()
        try:
            control_socket_path().unlink()
        except OSError:
            pass

    async def restart_link(self):
        """Start, or restart, the link listener for the phone paired now.

        The trust store is the paired phone's certificate, fixed when the
        listener starts, so pairing, unpairing and switching the link on or
        off all come through here.
        """
        if self._link_runner is not None:
            for ws in list(self._sockets):
                try:
                    await ws.close(code=1001, message=b"link closed")
                except Exception:  # noqa: BLE001 - it is going away either way
                    pass
            self._sockets.clear()
            await self._link_runner.cleanup()
            self._link_runner = None
        if not self.config["enabled"] or self.phone is None:
            return False

        app = web.Application(middlewares=[self._guard], client_max_size=1024 ** 2)
        self._routes(app)
        # A short shutdown: a link being closed must not stay half-open for
        # the minute aiohttp would otherwise give lingering connections.
        runner = web.AppRunner(app, access_log=None, shutdown_timeout=1.0)
        await runner.setup()
        context = identity.link_context(self.key_path, self.cert_path, self.phone["cert_pem"])
        try:
            await web.TCPSite(runner, host="0.0.0.0", port=self.port, ssl_context=context).start()
        except OSError as error:
            # Something else has the port (a second copy of this daemon,
            # usually). Say so and stay up: the control socket still works.
            await runner.cleanup()
            self.problem = f"cannot listen on port {self.port}: {error.strerror or error}"
            self.audit.write("", "error", self.problem)
            print(f"Adaptive Link: {self.problem}", flush=True)
            return False
        self.problem = ""
        self._link_runner = runner
        return True

    @property
    def listening(self):
        return self._link_runner is not None

    # ---------------------------------------------------------------- guard

    @web.middleware
    async def _guard(self, request, handler):
        peer = request.transport.get_extra_info("peername") if request.transport else None
        address = peer[0] if peer else ""
        if not identity.peer_allowed(address, self.config["allow_public"]):
            self.audit.write(address, "refused", "address is not on a private network")
            return json_error(403, "this network is not allowed")

        # TLS has already required the paired certificate. Compare it again
        # with what is stored, so a mistake in building the TLS context could
        # never by itself let a different certificate through.
        ssl_object = request.transport.get_extra_info("ssl_object")
        der = ssl_object.getpeercert(binary_form=True) if ssl_object else None
        if not der or self.phone is None or identity.fingerprint(der) != self.phone["fingerprint"]:
            self.audit.write(address, "refused", "certificate is not the paired phone's")
            return json_error(403, "not the paired phone")

        request["peer"] = address
        self._notice(address)
        return await handler(request)

    def _notice(self, address):
        now = time.monotonic()
        if now - self._last_notice > CONNECT_NOTICE_EVERY_S:
            self.audit.write(address, "connected",
                             "direct tunnel" if identity.is_loopback(address) else "local network")
            if self.config["notify_on_connect"]:
                desktop.notify(f"{self.phone['name']} connected",
                               "Your phone is connected to this computer.")
        self._last_notice = now

    def _track(self, ws):
        self._sockets = {open_ws for open_ws in self._sockets if not open_ws.closed}
        self._sockets.add(ws)

    def _allowed(self, switch):
        return bool(self.config.get(switch))

    # --------------------------------------------------------------- routes

    def _routes(self, app):
        add = app.router
        add.add_get("/v1/status", self.h_status)
        add.add_get("/v1/screen", self.h_screen)
        add.add_get("/v1/input", self.h_input)
        add.add_get("/v1/exec", self.h_exec)
        add.add_get("/v1/camera", self.h_camera)
        add.add_get("/v1/media", self.h_media_get)
        add.add_post("/v1/media", self.h_media_post)
        add.add_post("/v1/volume", self.h_volume)
        add.add_get("/v1/clipboard", self.h_clipboard_get)
        add.add_post("/v1/clipboard", self.h_clipboard_set)
        add.add_post("/v1/notify", self.h_notify)
        add.add_post("/v1/notify/dismiss", self.h_notify_dismiss)
        add.add_post("/v1/power", self.h_power)
        add.add_get("/v1/apps", self.h_apps)
        add.add_post("/v1/launch", self.h_launch)
        add.add_get("/v1/files", self.h_files)
        add.add_get("/v1/file", self.h_file)
        add.add_post("/v1/upload", self.h_upload)
        add.add_post("/v1/open", self.h_open)
        add.add_get("/v1/log", self.h_log)
        add.add_get("/v1/tasks", self.h_tasks)
        add.add_post("/v1/tasks/signal", self.h_task_signal)
        add.add_get("/v1/devices", self.h_devices)
        add.add_post("/v1/devices", self.h_device_action)
        add.add_get("/v1/network", self.h_network)
        add.add_post("/v1/network", self.h_network_action)
        add.add_post("/v1/keep", self.h_keep)
        add.add_get("/v1/desktop", self.h_desktop)
        add.add_get("/v1/desktop/report", self.h_desktop_report)
        add.add_post("/v1/desktop", self.h_desktop_action)

    async def h_status(self, request):
        info = await asyncio.to_thread(desktop.status)
        info.update({
            "version": VERSION,
            # From this machine itself means through the direct tunnel.
            "via": "direct" if identity.is_loopback(request["peer"]) else "lan",
            # Where this computer can be reached now. The phone keeps these,
            # so a changed address at home does not mean pairing again.
            "hosts": [address for address, _kind in await asyncio.to_thread(identity.local_addresses)],
            "screen": list(self.input.screen),
            "can": {"control": self._allowed("allow_input"),
                    "exec": self._allowed("allow_exec"), "files": self._allowed("allow_files"),
                    "power": self._allowed("allow_power"), "input": self.input.available,
                    "camera": camera.find_device() is not None},
        })
        return web.json_response(info)

    # ----------------------------------------------------- screen and input

    async def _read_input(self, ws):
        """Apply the input events arriving on a socket until it closes.

        With input turned off the socket is still read (so a close is seen)
        and what arrives is dropped: the phone may watch, not act.
        """
        async for message in ws:
            if message.type != WSMsgType.TEXT or not self._allowed("allow_input"):
                continue
            try:
                event = json.loads(message.data)
            except ValueError:
                continue
            await self.input.send(event)

    async def _have_screen(self):
        # The daemon can start before the graphical session is up; look again
        # rather than staying blind until it is restarted.
        return self.input.available or await self.input.start()

    async def h_screen(self, request):
        if not await self._have_screen():
            return json_error(503, "there is no screen to show")
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=64 * 1024)
        await ws.prepare(request)
        self._track(ws)
        capture = screen.Capture(self.input.screen, request.query.get("preset", "medium"))
        self.audit.write(request["peer"], "screen", capture.preset)
        self._sessions += 1
        try:
            await asyncio.to_thread(capture.start)
            reader = asyncio.ensure_future(self._read_input(ws))
            while not ws.closed and not reader.done():
                frame = await asyncio.to_thread(capture.next_frame, 1.0)
                if frame is not None:
                    await ws.send_bytes(frame)
            reader.cancel()
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            self._sessions -= 1
            await asyncio.to_thread(capture.stop)
        return ws

    async def h_input(self, request):
        """Trackpad, keyboard, remote and presenter: input with no picture."""
        if not self._allowed("allow_input"):
            return json_error(403, "pointer and keyboard are turned off on the computer")
        if not await self._have_screen():
            return json_error(503, "there is no screen to control")
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=64 * 1024)
        await ws.prepare(request)
        self._track(ws)
        self.audit.write(request["peer"], "input")
        await self._read_input(ws)
        return ws

    # ------------------------------------------------------------- commands

    def _kill(self, process):
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass

    async def h_exec(self, request):
        """Run a command for the owner and stream what it prints.

        One socket, one command: {"cmd": "...", "cwd": "~", "detach": false}.
        Output comes back as {"o": text}, then {"exit": code}. {"kill": true}
        stops it. A detached command (a player, an app) is started and left
        running; anything else ends with the socket.
        """
        if not self._allowed("allow_exec"):
            return json_error(403, "running commands is turned off on the computer")
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=64 * 1024)
        await ws.prepare(request)
        self._track(ws)

        first = await ws.receive()
        try:
            order = json.loads(first.data) if first.type == WSMsgType.TEXT else {}
        except ValueError:
            order = {}
        command = order.get("cmd") if isinstance(order, dict) else None
        if not isinstance(command, str) or not command.strip() or len(command) > 8000:
            await ws.send_json({"error": "no command"})
            await ws.close()
            return ws

        cwd = desktop.resolve(order.get("cwd"))
        if not cwd.is_dir():
            cwd = Path.home()
        self.audit.write(request["peer"], "exec", command)

        if order.get("detach"):
            process = await asyncio.create_subprocess_exec(
                "bash", "-lc", command, cwd=str(cwd), start_new_session=True,
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL)
            await ws.send_json({"started": process.pid})
            await ws.close()
            return ws

        process = await asyncio.create_subprocess_exec(
            "bash", "-lc", command, cwd=str(cwd), start_new_session=True,
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT)
        self._children.add(process)

        async def pump():
            while True:
                chunk = await process.stdout.read(EXEC_OUTPUT_CHUNK)
                if not chunk:
                    break
                await ws.send_json({"o": chunk.decode("utf-8", "replace")})
            await ws.send_json({"exit": await process.wait()})

        async def listen():
            async for message in ws:
                if message.type == WSMsgType.TEXT and '"kill"' in message.data:
                    self._kill(process)

        pumping = asyncio.ensure_future(pump())
        listening = asyncio.ensure_future(listen())
        try:
            await asyncio.wait({pumping, listening}, return_when=asyncio.FIRST_COMPLETED)
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            if process.returncode is None:
                self._kill(process)
            for task in (pumping, listening):
                task.cancel()
            self._children.discard(process)
            if not ws.closed:
                await ws.close()
        return ws

    # --------------------------------------------------------------- camera

    async def h_camera(self, request):
        device = camera.find_device()
        if device is None:
            return json_error(503, "the virtual camera is not installed (scripts/install-link-camera.sh)")
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=4 * 1024 * 1024)
        await ws.prepare(request)
        self._track(ws)
        webcam = camera.Webcam(device)
        self.audit.write(request["peer"], "camera", device)
        try:
            await asyncio.to_thread(webcam.start)
            async for message in ws:
                if message.type == WSMsgType.BINARY:
                    webcam.push(message.data)
        finally:
            await asyncio.to_thread(webcam.stop)
        return ws

    # ------------------------------------------------- media, sound, clipboard

    async def h_media_get(self, _request):
        return web.json_response({"players": await asyncio.to_thread(desktop.players),
                                  "volume": await asyncio.to_thread(desktop.volume)})

    async def h_media_post(self, request):
        data = await read_json(request)
        ok = await asyncio.to_thread(desktop.media, data.get("action"), str(data.get("player") or ""),
                                     data.get("seconds", 0))
        return web.json_response({"ok": bool(ok)})

    async def h_volume(self, request):
        data = await read_json(request)
        ok = await asyncio.to_thread(desktop.set_volume, data.get("action"))
        return web.json_response({"ok": bool(ok), "volume": await asyncio.to_thread(desktop.volume)})

    async def h_clipboard_get(self, request):
        self.audit.write(request["peer"], "clipboard-read")
        return web.json_response({"text": await asyncio.to_thread(desktop.clipboard_get)})

    async def h_clipboard_set(self, request):
        data = await read_json(request)
        return web.json_response({"ok": await asyncio.to_thread(desktop.clipboard_set, data.get("text"))})

    # -------------------------------------------------------- notifications

    async def h_notify(self, request):
        data = await read_json(request)
        ok = await asyncio.to_thread(self.notifications.show, data.get("key", ""), data.get("app", ""),
                                     data.get("title", ""), data.get("text", ""))
        return web.json_response({"ok": ok})

    async def h_notify_dismiss(self, request):
        data = await read_json(request)
        return web.json_response({"ok": await asyncio.to_thread(self.notifications.dismiss, data.get("key", ""))})

    # ---------------------------------------------------- power, apps, files

    async def h_power(self, request):
        if not self._allowed("allow_power"):
            return json_error(403, "power actions are turned off on the computer")
        action = (await read_json(request)).get("action")
        if action not in desktop.POWER_ACTIONS:
            return json_error(400, "unknown action")
        self.audit.write(request["peer"], "power", action)
        return web.json_response({"ok": await asyncio.to_thread(desktop.power, action)})

    # ------------------------------------- the machine, and the desktop's own

    async def h_tasks(self, request):
        # Command lines can carry anything; seeing them goes with running them.
        if not self._allowed("allow_exec"):
            return json_error(403, "commands are turned off on the computer")
        sort = "memory" if request.query.get("sort") == "memory" else "cpu"
        found = await asyncio.to_thread(system.processes, sort, request.query.get("q", "")[:80])
        return web.json_response({"summary": await asyncio.to_thread(system.summary), "processes": found})

    async def h_task_signal(self, request):
        if not self._allowed("allow_exec"):
            return json_error(403, "commands are turned off on the computer")
        body = await read_json(request)
        pid, action, tree = body.get("pid"), body.get("action"), body.get("tree") is True
        done, why = await asyncio.to_thread(system.signal_process, pid, action, tree)
        self.audit.write(request["peer"], "task",
                         f"{action} {pid}" + (" and what it started" if tree else "") + ("" if done else f" - {why}"))
        return web.json_response({"ok": done, "error": why})

    async def h_devices(self, _request):
        return web.json_response({"usb": await asyncio.to_thread(system.usb_devices),
                                  "drives": await asyncio.to_thread(system.drives)})

    async def h_device_action(self, request):
        if not self._allowed("allow_input"):
            return json_error(403, "the computer is view-only")
        body = await read_json(request)
        action, target = str(body.get("action", ""))[:20], str(body.get("target", ""))[:80]
        change = None
        if action in ("usb-on", "usb-off"):
            done, text, change = await asyncio.to_thread(system.usb_switch, target, action == "usb-on")
        else:
            done, text = await asyncio.to_thread(system.drive_action, target, action)
        self.audit.write(request["peer"], "device", f"{action} {target}" + ("" if done else f" - {text}"))
        return web.json_response({"ok": done, "text" if done else "error": text, "keep": self._hold(change)})

    async def h_network(self, _request):
        return web.json_response(await asyncio.to_thread(system.network))

    async def h_network_action(self, request):
        if not self._allowed("allow_input"):
            return json_error(403, "the computer is view-only")
        body = await read_json(request)
        action, value = str(body.get("action", ""))[:20], str(body.get("value", ""))[:80]
        # One change at a time: the one before is settled, kept, first.
        self._hold(None)
        done, text, change = await asyncio.to_thread(system.network_action, action, value, body.get("secret", ""))
        if action != "scan":
            self.audit.write(request["peer"], "network", f"{action} {value}".strip() + ("" if done else f" - {text}"))
        return web.json_response({"ok": done, "text" if done else "error": text, "keep": self._hold(change)})

    # A change that may have cut the phone off is undone unless the phone
    # comes back, over the link, to say it can still reach the computer.

    def _hold(self, change):
        """Wait for the phone to keep `change`. Returns how long it has."""
        if self._undo is not None:
            self._undo.cancel()   # what was waiting is kept: the phone got through to ask for this
            self._undo = None
        if change is None:
            return 0
        self._undo = asyncio.get_running_loop().create_task(self._undo_later(change))
        return KEEP_S

    async def _undo_later(self, change):
        await asyncio.sleep(KEEP_S)
        self._undo = None
        said = await asyncio.to_thread(system.undo, change)
        self.audit.write("-", "undone", f"{said}: the phone did not come back")

    async def h_keep(self, _request):
        waiting = self._undo is not None
        self._hold(None)
        return web.json_response({"ok": True, "kept": waiting})

    async def h_desktop(self, _request):
        return web.json_response(await asyncio.to_thread(system.desktop_state))

    async def h_desktop_report(self, request):
        done, text = await asyncio.to_thread(system.desktop_report, request.query.get("name", ""))
        return web.json_response({"ok": done, "text": text})

    async def h_desktop_action(self, request):
        if not self._allowed("allow_input"):
            return json_error(403, "pointer and keyboard are turned off on the computer")
        body = await read_json(request)
        action, value = str(body.get("action", ""))[:40], body.get("value", "")
        done, text = await asyncio.to_thread(system.desktop_action, action, value)
        shown = "" if action == "note" else str(value)[:60]   # what was noted is the owner's, not the log's
        self.audit.write(request["peer"], "desktop", f"{action} {shown}".strip())
        return web.json_response({"ok": done, "text": text})

    async def h_apps(self, _request):
        return web.json_response({"apps": await asyncio.to_thread(desktop.applications)})

    async def h_launch(self, request):
        if not self._allowed("allow_input"):
            return json_error(403, "pointer and keyboard are turned off on the computer")
        app_id = (await read_json(request)).get("id")
        self.audit.write(request["peer"], "launch", app_id)
        return web.json_response({"ok": await asyncio.to_thread(desktop.launch, app_id)})

    async def h_files(self, request):
        if not self._allowed("allow_files"):
            return json_error(403, "file access is turned off on the computer")
        try:
            listing = await asyncio.to_thread(desktop.list_directory, request.query.get("path"))
        except OSError as error:
            return json_error(404, error.strerror or "cannot read that folder")
        return web.json_response(listing)

    async def h_file(self, request):
        if not self._allowed("allow_files"):
            return json_error(403, "file access is turned off on the computer")
        path = desktop.resolve(request.query.get("path"))
        if not path.is_file():
            return json_error(404, "no such file")
        self.audit.write(request["peer"], "download", path)
        return web.FileResponse(path)

    async def h_upload(self, request):
        if not self._allowed("allow_files"):
            return json_error(403, "file access is turned off on the computer")
        target = desktop.upload_target(request.query.get("name"))
        target.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        try:
            with target.open("wb") as handle:
                async for chunk in request.content.iter_chunked(256 * 1024):
                    handle.write(chunk)
                    size += len(chunk)
        except (OSError, asyncio.CancelledError):
            target.unlink(missing_ok=True)
            raise
        self.audit.write(request["peer"], "upload", f"{target} ({size} bytes)")
        return web.json_response({"ok": True, "path": str(target), "size": size})

    async def h_open(self, request):
        if not self._allowed("allow_files"):
            return json_error(403, "file access is turned off on the computer")
        path = (await read_json(request)).get("path")
        self.audit.write(request["peer"], "open", path)
        return web.json_response({"ok": await asyncio.to_thread(desktop.open_path, path)})

    async def h_log(self, _request):
        return web.json_response({"entries": self.audit.tail(100)})

    # -------------------------------------------------------------- pairing

    def pairing_state(self):
        state = dict(self._pairing)
        for private in ("token", "cert_pem", "ui", "cloud_id"):
            state.pop(private, None)
        if state.get("expires"):
            state["seconds_left"] = max(0, int(state["expires"] - time.time()))
        state["reached"] = dict(self._pair_reached)
        return state

    def _show_pairing_request(self):
        """Put the request in front of the owner.

        A request that only raised a notification could not be answered: a
        notification has nowhere to press Pair. Unless the pairing window is
        already open (it shows the request itself), open it now, attached to
        this pairing rather than starting another.
        """
        if self._pairing.get("ui"):
            return
        try:
            import subprocess
            import sys
            subprocess.Popen([sys.executable, str(Path(__file__).with_name("pair_window.py")), "--attach"],
                             start_new_session=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._pairing["ui"] = True
        except OSError:
            pass

    async def _open_pair_listener(self):
        """The port a phone pairing by code talks to. Idempotent."""
        if self._pair_runner is not None:
            return
        app = web.Application(client_max_size=64 * 1024)
        app.router.add_post("/pair", self.h_pair)
        app.router.add_get("/pair/wait", self.h_pair_wait)
        runner = web.AppRunner(app, access_log=None, shutdown_timeout=1.0)
        await runner.setup()
        context = identity.pairing_context(self.key_path, self.cert_path)
        # A phone that cannot pair shows up here first: whether anything
        # reached the port at all, and what TLS said about it. A handshake
        # that fails never becomes a request, so it is counted at this level.
        self._pair_reached = {"hellos": 0, "alerts": []}

        def tls_event(_conn, direction, _version, content_type, msg_type, _data):
            name = getattr(msg_type, "name", str(msg_type))
            if direction == "read" and name == "CLIENT_HELLO":
                self._pair_reached["hellos"] += 1
            elif getattr(content_type, "name", "") == "ALERT":
                self._pair_reached["alerts"] = (self._pair_reached["alerts"] + [f"{direction} {name}"])[-5:]

        if hasattr(context, "_msg_callback"):
            context._msg_callback = tls_event
        try:
            await web.TCPSite(runner, host="0.0.0.0", port=self.pairing_port, ssl_context=context).start()
        except OSError as error:
            await runner.cleanup()
            self.problem = f"cannot listen on port {self.pairing_port}: {error.strerror or error}"
            return
        self._pair_runner = runner

    async def _close_pair_listener(self, delay):
        runner, self._pair_runner = self._pair_runner, None
        if runner is not None:
            # A moment for the phone to collect the answer it is waiting on.
            await asyncio.sleep(delay)
            await runner.cleanup()

    async def start_pairing(self, seconds=None, ui=False):
        """Start pairing by code. Returns what the QR code holds.

        Two minutes by default. A typed code takes longer than a scan, so the
        owner can ask for up to ten.
        """
        try:
            window = max(30, min(int(seconds), identity.PAIRING_WINDOW_MAX_S))
        except (TypeError, ValueError):
            window = identity.PAIRING_WINDOW_S
        await self.cancel_pairing()
        token = identity.new_pairing_token()
        hosts = [address for address, _kind in identity.local_addresses()]
        await self._open_pair_listener()

        self._pairing = {"state": "waiting", "token": token, "attempts": 0, "ui": bool(ui),
                         "expires": time.time() + window}
        self._pair_decided = asyncio.Event()
        self._arm_pair_timer(window)
        payload = identity.pairing_payload(socket.gethostname(), hosts, self.port,
                                           self.pairing_port, self.fingerprint, token)
        return {
            "payload": payload, "text": identity.pairing_text(payload),
            "hosts": hosts, "fingerprint": self.fingerprint,
            "seconds": window,
        }

    def _arm_pair_timer(self, seconds):
        if self._pair_timer is not None:
            self._pair_timer.cancel()
        self._pair_timer = asyncio.get_running_loop().call_later(
            seconds, lambda: asyncio.ensure_future(self._expire_pairing()))

    async def _expire_pairing(self):
        if self._pairing.get("state") in ("waiting", "pending"):
            await self._close_pairing("expired")

    async def _close_pairing(self, state):
        if self._pair_timer is not None:
            self._pair_timer.cancel()
            self._pair_timer = None
        # The answer is kept for the phone that asked by code, and nobody else.
        self._pairing = {"state": state, "token": self._pairing.get("token", "")}
        self._pair_decided.set()
        await self._close_pair_listener(0.5 if state in ("idle", "expired") else 3)

    async def cancel_pairing(self):
        if self._pairing.get("state") != "idle" or self._pair_runner is not None:
            await self._close_pairing("idle")

    def _too_many(self, address):
        """Whether this address has asked the pairing port too often.

        The port answers devices that are not trusted yet; this bounds what
        answering them can cost.
        """
        now = time.monotonic()
        recent = [t for t in self._pair_asks.get(address, []) if now - t < 60]
        recent.append(now)
        self._pair_asks[address] = recent[-PAIR_ASKS_PER_MINUTE - 1:]
        if len(self._pair_asks) > 500:
            self._pair_asks = {address: self._pair_asks[address]}
        return len(recent) > PAIR_ASKS_PER_MINUTE

    def _pair_peer(self, request):
        peer = request.transport.get_extra_info("peername") if request.transport else None
        return (peer[0], peer[1]) if peer else ("", 0)

    def _request_pairing(self, name, pem, digest, origin, account="", cloud_id="", token=""):
        """A device has asked to be trusted: hold the request for the owner.

        However it arrived - by a pairing code on the local network, or
        through the owner's account - it ends up here, and the same thing
        happens: the owner is shown the device and six digits, and decides.
        Returns the six digits.
        """
        name = identity.clean_name(name)
        code = identity.pairing_code(self.fingerprint, digest)
        ui = self._pairing.get("ui", False) if self._pairing.get("state") == "waiting" else False
        self._pairing = {"state": "pending", "name": name, "code": code, "ui": ui,
                         "cert_pem": pem.decode() if isinstance(pem, bytes) else pem,
                         "fingerprint": digest, "from": origin, "account": account,
                         "cloud_id": cloud_id, "token": token,
                         "expires": time.time() + identity.PAIRING_WINDOW_S}
        self._pair_decided = asyncio.Event()
        self._arm_pair_timer(identity.PAIRING_WINDOW_S)
        who = f"{name} ({account})" if account else name
        self.audit.write(origin, "pairing-requested", who)
        return code

    def _announce_request(self):
        pending = self._pairing
        who = f"{pending['name']} ({pending['account']})" if pending.get("account") else pending["name"]
        code = pending["code"]
        desktop.notify("A phone wants to connect", f"{who} - check that it shows {code[:3]} {code[3:]}")
        self._show_pairing_request()

    async def h_pair(self, request):
        address, _port = self._pair_peer(request)
        if not identity.peer_allowed(address, self.config["allow_public"]):
            return json_error(403, "this network is not allowed")
        if self._too_many(address):
            return json_error(429, "too many requests; wait a minute")
        state = self._pairing.get("state")
        if state == "pending":
            return json_error(409, "another device is waiting to be answered")
        if state != "waiting":
            return json_error(409, "not waiting for a phone")

        data = await read_json(request)
        if not identity.tokens_match(data.get("t"), self._pairing["token"]):
            self._pairing["attempts"] += 1
            self.audit.write(address, "pairing-refused", "wrong code")
            if self._pairing["attempts"] >= identity.PAIRING_MAX_ATTEMPTS:
                asyncio.ensure_future(self._close_pairing("expired"))
            return json_error(403, "wrong pairing code")
        try:
            pem, _der, digest = identity.check_phone_certificate(data.get("cert", ""))
        except identity.BadCertificate as error:
            return json_error(400, str(error))

        code = self._request_pairing(data.get("name"), pem, digest, address, token=self._pairing["token"])
        self._announce_request()
        return web.json_response({"ok": True, "code": code, "host": socket.gethostname()})

    async def h_pair_wait(self, request):
        """The phone waits here for the owner's answer on the computer."""
        address, _port = self._pair_peer(request)
        if self._too_many(address):
            return json_error(429, "too many requests; wait a minute")
        if not identity.tokens_match(request.query.get("t"), self._pairing.get("token", "")):
            return json_error(403, "wrong pairing code")
        try:
            await asyncio.wait_for(self._pair_decided.wait(), 25)
        except asyncio.TimeoutError:
            pass
        return web.json_response({"state": self._pairing.get("state", "idle")})

    async def decide_pairing(self, accept):
        if self._pairing.get("state") != "pending":
            return False
        pending = self._pairing
        if accept:
            self.phone = identity.save_phone(pending["name"], pending["cert_pem"], self.link_dir)
            self.audit.write(pending.get("from", ""), "paired", pending["name"])
            await self.restart_link()
        else:
            self.audit.write(pending.get("from", ""), "pairing-rejected", pending["name"])
        if pending.get("cloud_id"):
            # Tell the phone, through the account, what the owner decided.
            self._decided[pending["cloud_id"]] = pending.get("cloud_at")
            await self._cloud_try(self.account.put(f"computers/{self.cloud_id}/accepted/{pending['cloud_id']}",
                                                   bool(accept)))
        await self._close_pairing("paired" if accept else "rejected")
        return True

    async def unpair(self):
        removed = identity.forget_phone(self.link_dir)
        self.phone = None
        self._decided.clear()
        await self.restart_link()
        if removed:
            self.audit.write("", "unpaired")
            if self.account is not None and self.account.signed_in:
                await self._cloud_try(self.account.delete(f"computers/{self.cloud_id}/accepted"))
        return removed

    async def set_enabled(self, enabled):
        self.config["enabled"] = bool(enabled)
        identity.save_config(self.config, self.link_dir)
        await self.restart_link()
        await self.restart_cloud()
        self.audit.write("", "enabled" if enabled else "disabled")

    # ------------------------------------------------------------ the account

    @property
    def cloud_id(self):
        return cloud.device_id(self.fingerprint)

    async def _cloud_try(self, awaitable):
        """Something for the account's space that may fail without mattering:
        it will be put right the next time the space is reached."""
        try:
            await awaitable
        except (cloud.CloudError, aiohttp.ClientError, asyncio.TimeoutError, OSError) as error:
            self.cloud_state = f"cannot reach the account: {error}"

    async def restart_cloud(self):
        """Start, or stop, this computer's presence in the owner's account.

        Present when: the owner's project is set up, they are signed in, the
        link is on and account_enroll is on. Then the computer keeps its name,
        fingerprint and addresses in the account's space and listens there for
        its own devices.
        """
        if self._cloud_task is not None:
            self._cloud_task.cancel()
            self._cloud_task = None
        if self._tunnel is not None:
            await self._tunnel.close()
            self._tunnel = None
        if self.account is not None:
            await self.account.close()

        project = cloud.load_project(self.link_dir)
        if project is None:
            self.account, self.cloud_state = None, "not set up"
            return
        self.account = cloud.Account(project, self.link_dir)
        if not self.account.signed_in:
            self.cloud_state = "signed out"
        elif not self.config["enabled"] or not self.config["account_enroll"]:
            self.cloud_state = "off"
        else:
            self.cloud_state = "connecting"
            self._cloud_task = asyncio.ensure_future(self._cloud_loop())

    async def _publish(self):
        hosts = [a for a, _kind in await asyncio.to_thread(identity.local_addresses)]
        await self.account.patch(f"computers/{self.cloud_id}", {
            "name": socket.gethostname(), "fingerprint": self.fingerprint,
            "hosts": hosts, "port": self.port, "at": int(time.time())})

    async def _republish(self):
        """Keep what the account says about this computer true: again every
        ten minutes, and at once when it moves to another network."""
        known, since = None, time.time()
        while True:
            await asyncio.sleep(20)
            hosts = [a for a, _kind in await asyncio.to_thread(identity.local_addresses)]
            if (known is not None and hosts != known and hosts) or time.time() - since > 600:
                await self._publish()
                since = time.time()
            known = hosts or known

    async def _cloud_loop(self):
        wait = 2
        while True:
            tasks = []
            try:
                await self._publish()
                self.cloud_state = "connected"
                wait = 2
                tasks = [asyncio.ensure_future(t) for t in (
                    self.account.watch(f"signals/{self.cloud_id}", self._on_signals),
                    self.account.watch("phones", self._on_phones),
                    self._republish())]
                # The streams end when the hourly token lapses, or on an
                # error; either way start again from a fresh publish.
                done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            except asyncio.CancelledError:
                raise
            except cloud.CloudError as error:
                self.cloud_state = str(error)
                if not self.account.signed_in:
                    return
                wait = min(wait * 2, 120)
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as error:
                self.cloud_state = f"cannot reach the account: {error.__class__.__name__}"
                wait = min(wait * 2, 120)
            finally:
                for task in tasks:
                    task.cancel()
            await asyncio.sleep(wait)

    @staticmethod
    def _entries(path, data):
        """What a change in the space says, as {name: value} of whole
        entries. Changes inside an entry (this computer's own answers) are
        not entries and give nothing."""
        parts = [part for part in path.split("/") if part]
        if not parts:
            return data if isinstance(data, dict) else {}
        if len(parts) == 1:
            return {parts[0]: data}
        return {}

    async def _on_signals(self, path, data):
        """A phone of the account asks for a direct connection."""
        for session, value in self._entries(path, data).items():
            if not isinstance(value, dict) or session in self._answered:
                continue
            self._answered.add(session)
            if len(self._answered) > 500:
                self._answered = {session}
            offer = value.get("offer")
            stale = abs(time.time() - float(value.get("at") or 0)) > SIGNAL_FRESH_S
            if stale or value.get("answer") or not isinstance(offer, str) or not self.listening:
                # Old, already answered, or nothing to connect to: clear it away.
                await self._cloud_try(self.account.delete(f"signals/{self.cloud_id}/{session}"))
                continue
            if self._tunnel is None:
                import rtc
                self._tunnel = rtc.TunnelServer(
                    self.port, report=lambda what: self.audit.write("account", "tunnel-state", what))
            try:
                answer = await asyncio.wait_for(self._tunnel.answer(offer), 30)
            except Exception as error:  # noqa: BLE001 - one bad offer must not stop the listener
                self.audit.write("account", "tunnel-refused", str(error)[:120])
                continue
            self.audit.write("account", "tunnel", "a direct connection was set up")
            await self._cloud_try(self.account.patch(f"signals/{self.cloud_id}/{session}", {"answer": answer}))

    async def _on_phones(self, path, data):
        """A phone signed in to the account says it wants this computer."""
        for phone_id, value in self._entries(path, data).items():
            if not isinstance(value, dict) or value.get("want") != self.cloud_id:
                continue
            try:
                pem, _der, digest = identity.check_phone_certificate(value.get("cert", ""))
            except identity.BadCertificate:
                continue
            if cloud.device_id(digest) != phone_id:
                continue   # the entry does not belong to the certificate in it

            try:
                asked = float(value.get("at") or 0)
            except (TypeError, ValueError):
                continue
            # Each request is answered once; asking again later is a new one.
            if self._decided.get(phone_id) == asked:
                continue
            if self.phone and self.phone["fingerprint"] == digest:
                # Already this computer's phone: say so.
                self._decided[phone_id] = asked
                await self._cloud_try(self.account.put(f"computers/{self.cloud_id}/accepted/{phone_id}", True))
                continue
            if abs(time.time() - asked) > REQUEST_FRESH_S or self._pairing.get("state") == "pending":
                continue

            self._request_pairing(value.get("name"), pem, digest, "account",
                                  account=self.account.email, cloud_id=phone_id)
            self._pairing["cloud_at"] = asked
            if self.config["auto_approve_account"]:
                await self.decide_pairing(True)
            else:
                self._announce_request()

    # -- signing in (from the control socket)

    async def setup_project(self, values):
        try:
            cloud.save_project(values, self.link_dir)
        except (KeyError, TypeError):
            return False
        if cloud.load_project(self.link_dir) is None:
            return False
        await self.restart_cloud()
        return True

    async def begin_sign_in(self):
        if self.account is None:
            return {"ok": False, "error": "the Google project is not set up (link-cli.py setup)"}
        try:
            started = await self.account.begin_sign_in()
        except (cloud.CloudError, aiohttp.ClientError, asyncio.TimeoutError, OSError) as error:
            return {"ok": False, "error": str(error) or error.__class__.__name__}
        self._signin = {"state": "waiting", "code": started["user_code"], "url": started["verification_url"]}

        async def finish():
            try:
                email = await self.account.finish_sign_in(started)
                self._signin = {"state": "done", "email": email}
                self.audit.write("", "signed-in", email)
                await self.restart_cloud()
            except (cloud.CloudError, aiohttp.ClientError, asyncio.TimeoutError, OSError) as error:
                self._signin = {"state": "failed", "error": str(error) or error.__class__.__name__}

        self._signin_task = asyncio.ensure_future(finish())
        return {"ok": True, "code": started["user_code"], "url": started["verification_url"]}

    async def sign_out(self):
        if self.account is None or not self.account.signed_in:
            return False
        await self._cloud_try(self.account.delete(f"computers/{self.cloud_id}"))
        self.account.sign_out()
        self.audit.write("", "signed-out")
        await self.restart_cloud()
        return True

    # -------------------------------------------------------------- control

    def describe(self):
        addresses = identity.local_addresses()
        return {
            "enabled": self.config["enabled"],
            "listening": self.listening,
            "problem": self.problem,
            "port": self.port,
            "phone": {"name": self.phone["name"], "paired_at": self.phone["paired_at"],
                      "fingerprint": self.phone["fingerprint"]} if self.phone else None,
            "addresses": [{"address": a, "kind": k} for a, k in addresses],
            "fingerprint": self.fingerprint,
            "viewing": self._sessions,
            "config": {k: self.config[k] for k in identity.DEFAULT_CONFIG},
            "camera": camera.find_device(),
            "pairing": self.pairing_state(),
            "account": self.account.email if self.account is not None else "",
            "cloud": self.cloud_state,
            "signin": dict(self._signin),
            "direct": self._tunnel.connected if self._tunnel is not None else 0,
        }

    async def _start_control(self):
        """The owner's side: a Unix socket in the user's runtime directory,
        which only this user can open."""
        app = web.Application()

        async def status(_request):
            return web.json_response(self.describe())

        async def pair_start(request):
            data = await read_json(request)
            return web.json_response(await self.start_pairing(data.get("seconds"), ui=bool(data.get("ui"))))

        async def pair_state(_request):
            return web.json_response(self.pairing_state())

        async def pair_decide(request):
            data = await read_json(request)
            return web.json_response({"ok": await self.decide_pairing(bool(data.get("accept")))})

        async def pair_cancel(_request):
            await self.cancel_pairing()
            return web.json_response({"ok": True})

        async def enable(request):
            await self.set_enabled(bool((await read_json(request)).get("enabled")))
            return web.json_response(self.describe())

        async def unpair(_request):
            return web.json_response({"ok": await self.unpair()})

        async def configure(request):
            data = await read_json(request)
            for key in ("allow_input", "allow_exec", "allow_files", "allow_power", "allow_public", "notify_on_connect",
                        "account_enroll", "auto_approve_account"):
                if isinstance(data.get(key), bool):
                    self.config[key] = data[key]
            identity.save_config(self.config, self.link_dir)
            if "account_enroll" in data:
                await self.restart_cloud()
            return web.json_response(self.describe())

        async def cloud_setup(request):
            return web.json_response({"ok": await self.setup_project(await read_json(request))})

        async def cloud_signin(_request):
            return web.json_response(await self.begin_sign_in())

        async def cloud_signout(_request):
            return web.json_response({"ok": await self.sign_out()})

        async def log(_request):
            return web.json_response({"entries": self.audit.tail(200)})

        app.router.add_get("/status", status)
        app.router.add_post("/pair/start", pair_start)
        app.router.add_get("/pair/state", pair_state)
        app.router.add_post("/pair/decide", pair_decide)
        app.router.add_post("/pair/cancel", pair_cancel)
        app.router.add_post("/enable", enable)
        app.router.add_post("/unpair", unpair)
        app.router.add_post("/configure", configure)
        app.router.add_get("/log", log)
        app.router.add_post("/cloud/setup", cloud_setup)
        app.router.add_post("/cloud/signin", cloud_signin)
        app.router.add_post("/cloud/signout", cloud_signout)

        path = control_socket_path()
        try:
            path.unlink()
        except OSError:
            pass
        runner = web.AppRunner(app, access_log=None, shutdown_timeout=1.0)
        await runner.setup()
        old_mask = os.umask(0o177)  # the socket is created 0600
        try:
            await web.UnixSite(runner, str(path)).start()
        finally:
            os.umask(old_mask)
        self._control_runner = runner


async def serve():
    link = Link(os.environ.get("ADAPTIVE_LINK_DIR"), os.environ.get("ADAPTIVE_LINK_STATE_DIR"))
    await link.start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    state = "listening" if link.listening else ("off" if not link.config["enabled"] else "no phone paired")
    print(f"Adaptive Link: {state} (port {link.port})", flush=True)
    await stop.wait()
    await link.stop()


if __name__ == "__main__":
    asyncio.run(serve())
