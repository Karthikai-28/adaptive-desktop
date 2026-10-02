"""Adaptive Link - the server the owner's paired phone talks to.

Three listeners, each for one kind of caller:

  the link     TCP, mutual TLS. Only the paired phone can finish a handshake
               (identity.link_context), so nothing below /v1 is reachable by
               anyone else. Not started at all until a phone is paired, and
               stopped when the link is turned off.
  pairing      TCP, TLS without a client certificate, open only for the two
               minutes after the owner asks to pair, and good for one phone.
  control      A Unix socket only this user can open: how the pairing window,
               link-cli and the palette talk to the daemon.

What a request may do is decided in three places before any handler runs:
the address it came from (identity.peer_allowed), the certificate it
presented (TLS, then checked again here against the stored fingerprint), and
the owner's switches in config.json (allow_exec, allow_files, allow_power).
Everything the phone does is written to the audit log.
"""

import asyncio
import json
import os
import signal
import socket
import time
from pathlib import Path

from aiohttp import WSMsgType, web

import camera
import desktop
import identity
import inputs
import screen

VERSION = 1
CONNECT_NOTICE_EVERY_S = 600
EXEC_OUTPUT_CHUNK = 4096


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
        self._last_notice = 0.0
        self.problem = ""
        self._sessions = 0
        self._children = set()
        # Every open socket to the phone, so that switching the link off or
        # unpairing ends what the phone is doing now, not at its next request.
        self._sockets = set()

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

    async def stop(self):
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
            self.audit.write(address, "refused", "address is not on a private or Tailscale network")
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
                             "tailscale" if identity.is_tailscale(address) else "local network")
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

    async def h_status(self, request):
        info = await asyncio.to_thread(desktop.status)
        info.update({
            "version": VERSION,
            "via": "tailscale" if identity.came_by_tailnet(request.host, request["peer"]) else "lan",
            # Where this computer can be reached now. The phone keeps these,
            # so a changed address at home does not mean pairing again.
            "hosts": [address for address, _kind in await asyncio.to_thread(identity.local_addresses)],
            "screen": list(self.input.screen),
            "can": {"exec": self._allowed("allow_exec"), "files": self._allowed("allow_files"),
                    "power": self._allowed("allow_power"), "input": self.input.available,
                    "camera": camera.find_device() is not None},
        })
        return web.json_response(info)

    # ----------------------------------------------------- screen and input

    async def _read_input(self, ws):
        """Apply the input events arriving on a socket until it closes."""
        async for message in ws:
            if message.type != WSMsgType.TEXT:
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

    async def h_apps(self, _request):
        return web.json_response({"apps": await asyncio.to_thread(desktop.applications)})

    async def h_launch(self, request):
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
        state.pop("token", None)
        state.pop("cert_pem", None)
        state.pop("ui", None)
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

    async def start_pairing(self, seconds=None, ui=False):
        """Open the pairing window. Returns what the QR code holds.

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
        await web.TCPSite(runner, host="0.0.0.0", port=self.pairing_port, ssl_context=context).start()
        self._pair_runner = runner

        self._pairing = {"state": "waiting", "token": token, "attempts": 0, "ui": bool(ui),
                         "expires": time.time() + window}
        self._pair_decided = asyncio.Event()
        self._pair_timer = asyncio.get_running_loop().call_later(
            window, lambda: asyncio.ensure_future(self._expire_pairing()))
        payload = identity.pairing_payload(socket.gethostname(), hosts, self.port,
                                           self.pairing_port, self.fingerprint, token)
        return {
            "payload": payload, "text": identity.pairing_text(payload),
            "hosts": hosts, "fingerprint": self.fingerprint,
            "seconds": window,
        }

    async def _expire_pairing(self):
        if self._pairing.get("state") in ("waiting", "pending"):
            await self._close_pairing("expired")

    async def _close_pairing(self, state):
        if self._pair_timer is not None:
            self._pair_timer.cancel()
            self._pair_timer = None
        self._pairing = {"state": state}
        self._pair_decided.set()
        runner, self._pair_runner = self._pair_runner, None
        if runner is not None:
            # A moment for the phone to collect the answer it is waiting on.
            await asyncio.sleep(0.5 if state in ("idle", "expired") else 3)
            await runner.cleanup()

    async def cancel_pairing(self):
        if self._pair_runner is not None or self._pairing.get("state") != "idle":
            await self._close_pairing("idle")

    def _pair_peer(self, request):
        peer = request.transport.get_extra_info("peername") if request.transport else None
        return peer[0] if peer else ""

    async def h_pair(self, request):
        address = self._pair_peer(request)
        if not identity.peer_allowed(address, self.config["allow_public"]):
            return json_error(403, "this network is not allowed")
        if self._pairing.get("state") != "waiting":
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

        name = identity.clean_name(data.get("name"))
        code = identity.pairing_code(self.fingerprint, digest)
        self._pairing.update({"state": "pending", "name": name, "code": code,
                              "cert_pem": pem.decode(), "fingerprint": digest, "from": address})
        self.audit.write(address, "pairing-requested", name)
        desktop.notify("A phone wants to pair", f"{name} - check that it shows {code[:3]} {code[3:]}")
        self._show_pairing_request()
        return web.json_response({"ok": True, "code": code, "host": socket.gethostname()})

    async def h_pair_wait(self, request):
        """The phone waits here for the owner's answer on the computer."""
        if not identity.tokens_match(request.query.get("t"), self._pairing.get("token", "")) \
                and self._pairing.get("state") not in ("paired", "rejected", "expired"):
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
        await self._close_pairing("paired" if accept else "rejected")
        return True

    async def unpair(self):
        removed = identity.forget_phone(self.link_dir)
        self.phone = None
        await self.restart_link()
        if removed:
            self.audit.write("", "unpaired")
        return removed

    async def set_enabled(self, enabled):
        self.config["enabled"] = bool(enabled)
        identity.save_config(self.config, self.link_dir)
        await self.restart_link()
        self.audit.write("", "enabled" if enabled else "disabled")

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
            "tailscale": any(kind == "tailscale" for _a, kind in addresses),
            "fingerprint": self.fingerprint,
            "viewing": self._sessions,
            "config": {k: self.config[k] for k in identity.DEFAULT_CONFIG},
            "camera": camera.find_device(),
            "pairing": self.pairing_state(),
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
            for key in ("allow_exec", "allow_files", "allow_power", "allow_public", "notify_on_connect"):
                if isinstance(data.get(key), bool):
                    self.config[key] = data[key]
            identity.save_config(self.config, self.link_dir)
            return web.json_response(self.describe())

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
