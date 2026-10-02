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
import contextvars
import json
import os
import signal
import socket
import time
from pathlib import Path

import aiohttp
from aiohttp import WSMsgType, web

import actions
import alerts
import camera
import cloud
import companion
import desktop
import identity
import inputs
import machine
import scenes
import screen
import system

VERSION = 1
CONNECT_NOTICE_EVERY_S = 600
# How long the phone has to say it can still reach the computer after a
# change that may have cut it off.
KEEP_S = int(os.environ.get("ADAPTIVE_LINK_KEEP_S", "45"))
# How often the machine is looked at for something worth telling the phone.
ALERT_EVERY_S = float(os.environ.get("ADAPTIVE_LINK_ALERT_EVERY_S", "30"))
# How long the phone may be gone from the network before the computer locks.
PROXIMITY_GRACE_S = float(os.environ.get("ADAPTIVE_LINK_PROXIMITY_S", "60"))
# What a phone may ask to be told (/v1/events), and the owner's switch each needs.
EVENT_KINDS = {"notification": "send_notifications", "alert": None, "clipboard": "sync_clipboard",
               "approve": "allow_power", "approve-done": "allow_power", "ring": None, "sms-send": None,
               # The phone's own screen shown here: what is done in its window, and being asked to start.
               "phone-input": None, "cast": None,
               # Something the computer offers to do, for the phone to say yes to with one tap.
               "offer": None}
# What a phone may ask to be kept told about (/v1/watch): how to read each, and how often to look.
WATCHED = {
    "status": (lambda: desktop.status(), 5), "media": (lambda: {"players": desktop.players(), "volume": desktop.volume()}, 2),
    "network": (system.network, 2), "devices": (lambda: {"usb": system.usb_devices(), "drives": system.drives()}, 3),
    "desktop": (system.desktop_state, 5),
    **{name: (read, 4) for name, read in machine.READ.items()},
}
# How often the situation is looked at for a scene come round again.
SCENE_EVERY_S = float(os.environ.get("ADAPTIVE_LINK_SCENE_EVERY_S", "10"))
EXEC_OUTPUT_CHUNK = 4096
PAIR_ASKS_PER_MINUTE = 60
# How old a request made through the account may be and still be acted on.
SIGNAL_FRESH_S = 120
REQUEST_FRESH_S = 600


# The device whose request is being handled: what it may do can be less than
# what the others may (identity.PHONE_SWITCHES).
CALLER = contextvars.ContextVar("caller", default=None)


class Audit(desktop.Audit):
    """The record, saying which device did each thing when there are several."""

    def __init__(self, path, several):
        super().__init__(path)
        self._several = several

    def write(self, peer, action, detail=""):
        caller = CALLER.get()
        if caller and peer and self._several():
            peer = f"{peer} {caller['name']}"
        super().write(peer, action, detail)


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
        self.phones = identity.load_phones(self.link_dir)
        self.audit = Audit(self.state_dir / "link.log", lambda: len(self.phones) > 1)
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
        self._last_notice = {}
        self.problem = ""
        self._sessions = 0
        self._children = set()
        # Every open socket to the phone, so that switching the link off or
        # unpairing ends what the phone is doing now, not at its next request.
        self._sockets = set()
        self._undo = None   # a change waiting for the phone to keep it
        # What the computer tells the phone without being asked (alerts.py).
        self.events = alerts.Events()
        self._watchers = []
        # The owner's relay, if they run one, and the screen as video (media.py).
        self.relay = identity.load_relay(self.link_dir)
        self._media = None
        # The phone and the computer as a pair (companion.py).
        self.approvals = companion.Approvals(self.events)
        # The checks say the phone is really gone without waiting for a
        # network to stop answering.
        probing = os.environ.get("ADAPTIVE_LINK_PROXIMITY_PROBE") != "0"
        self.presence = companion.Presence(PROXIMITY_GRACE_S, self._phone_gone,
                                           companion.reachable if probing else (lambda _address: False))
        self.phonebook = companion.PhoneBook()
        self._clip_from_phone = ""
        self._texts = {}   # texts the phone has been asked to send: id -> whether it did
        self._phone_screen = None   # a phone's screen being shown here (phone_screen.py)
        # One way in to everything (actions.py), and the situations that come round again (scenes.py).
        self.book = actions.Book(self.link_dir)
        self.scenes = scenes.Scenes(self.link_dir)
        self._nearby = None   # this computer saying it is here, while it waits to be paired with
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
        self._watchers = [asyncio.ensure_future(alerts.watch_notifications(self.events)),
                          asyncio.ensure_future(alerts.watch_machine(self.events, ALERT_EVERY_S)),
                          asyncio.ensure_future(companion.watch_clipboard(
                              self.events, desktop.clipboard_get,
                              lambda: self.config["sync_clipboard"] and self.events.listening("clipboard"),
                              lambda: self._clip_from_phone)),
                          asyncio.ensure_future(self._watch_scenes())]

    async def stop(self):
        for watcher in self._watchers:
            watcher.cancel()
        if self._media is not None:
            await self._media.close_all()
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

    @property
    def phone(self):
        """The device paired last, for what speaks of "the phone"."""
        return self.phones[-1] if self.phones else None

    async def restart_link(self):
        """Start, or restart, the link listener for the devices paired now.

        The trust store is the paired devices' certificates, fixed when the
        listener starts, so pairing, unpairing and switching the link on or
        off all come through here.
        """
        if self._media is not None:
            await self._media.close_all()
        if self._phone_screen is not None:
            await self._phone_screen.close()
        if self._link_runner is not None:
            for ws in list(self._sockets):
                try:
                    await ws.close(code=1001, message=b"link closed")
                except Exception:  # noqa: BLE001 - it is going away either way
                    pass
            self._sockets.clear()
            await self._link_runner.cleanup()
            self._link_runner = None
        if not self.config["enabled"] or not self.phones:
            return False

        app = web.Application(middlewares=[self._guard], client_max_size=1024 ** 2)
        self._routes(app)
        # A short shutdown: a link being closed must not stay half-open for
        # the minute aiohttp would otherwise give lingering connections.
        runner = web.AppRunner(app, access_log=None, shutdown_timeout=1.0)
        await runner.setup()
        context = identity.link_context(self.key_path, self.cert_path, [phone["cert_pem"] for phone in self.phones])
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

        # TLS has already required a paired certificate. Compare it again
        # with what is stored, so a mistake in building the TLS context could
        # never by itself let a different certificate through. It is also
        # what says which of the paired devices this is.
        ssl_object = request.transport.get_extra_info("ssl_object")
        der = ssl_object.getpeercert(binary_form=True) if ssl_object else None
        digest = identity.fingerprint(der) if der else ""
        caller = next((phone for phone in self.phones if phone["fingerprint"] == digest), None)
        if caller is None:
            self.audit.write(address, "refused", "certificate is not a paired phone's")
            return json_error(403, "not a paired phone")

        request["peer"] = address
        request["phone"] = caller
        CALLER.set(caller)
        self._notice(address, caller)
        return await handler(request)

    def _notice(self, address, caller):
        now = time.monotonic()
        if now - self._last_notice.get(caller["fingerprint"], -CONNECT_NOTICE_EVERY_S - 1) > CONNECT_NOTICE_EVERY_S:
            self.audit.write(address, "connected",
                             "direct tunnel" if identity.is_loopback(address) else "local network")
            if self.config["notify_on_connect"]:
                desktop.notify(f"{caller['name']} connected",
                               "Your phone is connected to this computer.")
        self._last_notice[caller["fingerprint"]] = now

    def _track(self, ws):
        self._sockets = {open_ws for open_ws in self._sockets if not open_ws.closed}
        self._sockets.add(ws)

    def _allowed(self, switch):
        """Whether the device asking may: the owner's switch for all of them,
        and nothing held back from this one."""
        caller = CALLER.get()
        return bool(self.config.get(switch)) and not (caller and switch in caller.get("deny", ()))

    # --------------------------------------------------------------- routes

    def _routes(self, app):
        add = app.router
        add.add_get("/v1/status", self.h_status)
        add.add_get("/v1/screen", self.h_screen)
        add.add_get("/v1/input", self.h_input)
        add.add_post("/v1/rtc", self.h_rtc)
        add.add_post("/v1/rtc/close", self.h_rtc_close)
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
        add.add_post("/v1/open-url", self.h_open_url)
        add.add_get("/v1/log", self.h_log)
        add.add_get("/v1/events", self.h_events)
        add.add_post("/v1/approve", self.h_approve)
        add.add_post("/v1/phone/state", self.h_phone_state)
        add.add_post("/v1/phone/sms", self.h_phone_sms)
        add.add_post("/v1/phone/call", self.h_phone_call)
        add.add_post("/v1/phone/sent", self.h_phone_sent)
        add.add_get("/v1/mic", self.h_mic)
        add.add_post("/v1/ask", self.h_ask)
        add.add_post("/v1/do", self.h_do)
        add.add_get("/v1/actions", self.h_actions)
        add.add_post("/v1/chains", self.h_chains)
        add.add_get("/v1/watch", self.h_watch)
        add.add_get("/v1/doctor", self.h_doctor)
        add.add_get("/v1/front", self.h_front)
        add.add_post("/v1/phone/screen", self.h_phone_screen)
        add.add_post("/v1/phone/screen/close", self.h_phone_screen_close)
        add.add_get("/v1/tasks", self.h_tasks)
        add.add_post("/v1/tasks/signal", self.h_task_signal)
        add.add_get("/v1/devices", self.h_devices)
        add.add_post("/v1/devices", self.h_device_action)
        add.add_get("/v1/network", self.h_network)
        add.add_post("/v1/network", self.h_network_action)
        add.add_post("/v1/keep", self.h_keep)
        add.add_get("/v1/machine/services/log", self.h_service_log)
        add.add_get("/v1/machine/{what}", self.h_machine)
        add.add_post("/v1/machine/{what}", self.h_machine_action)
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
            # Where to send the packet that wakes this computer; kept by the
            # phone for when the computer is asleep and cannot say.
            "wake": await asyncio.to_thread(system.wake_addresses),
            # The owner's relay, for a phone that cannot reach the computer
            # directly from where it is. Said only here, to a paired phone.
            "relay": self.relay,
            "can": {"control": self._allowed("allow_input"),
                    "exec": self._allowed("allow_exec"), "files": self._allowed("allow_files"),
                    "power": self._allowed("allow_power"), "input": self.input.available,
                    "camera": camera.find_device() is not None},
        })
        return web.json_response(info)

    # ----------------------------------------------------- screen and input

    async def _read_input(self, ws, region=None):
        """Apply the input events arriving on a socket until it closes.

        With input turned off the socket is still read (so a close is seen)
        and what arrives is dropped: the phone may watch, not act. A key or
        button still held when the socket closes is let go of, so that a
        phone going out of reach never leaves one stuck down.
        """
        held = frozenset()
        try:
            async for message in ws:
                if message.type != WSMsgType.TEXT or not self._allowed("allow_input"):
                    continue
                try:
                    event = json.loads(message.data)
                except ValueError:
                    continue
                if await self.input.send(inputs.in_region(event, region, self.input.screen)):
                    held = inputs.held_after(held, event)
        finally:
            for event in inputs.release(held):
                await self.input.send(event)

    async def _region(self, request):
        """The one display the phone asked for (?display=NAME), or None for
        the whole screen."""
        name = request.query.get("display", "")
        return await asyncio.to_thread(machine.region, name) if name else None

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
        region = await self._region(request)
        capture = screen.Capture(self.input.screen, request.query.get("preset", "medium"), region)
        self.audit.write(request["peer"], "screen", capture.preset)
        self._sessions += 1
        try:
            await asyncio.to_thread(capture.start)
            reader = asyncio.ensure_future(self._read_input(ws, region))
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

    async def h_rtc(self, request):
        """The screen as video, with the computer's sound: the phone's offer
        comes in, the answer goes back, and the pictures then travel on a
        connection of their own between the two (media.py)."""
        if not await self._have_screen():
            return json_error(503, "there is no screen to show")
        body = await read_json(request)
        try:
            if self._media is None:
                import media
                self._media = media.MediaServer(
                    relay=self.relay, report=lambda what: self.audit.write("-", "screen-video", what))
            self._media.relay = self.relay
            region = await asyncio.to_thread(machine.region, str(body["display"])) if body.get("display") else None
            started = await asyncio.wait_for(self._media.answer(
                body.get("offer"), self.input.screen, str(body.get("preset", "medium")), body.get("sound") is not False,
                region), 30)
        except ImportError:
            return json_error(503, "video is not installed on the computer (see docs/ADAPTIVE_LINK.md)")
        except (ValueError, asyncio.TimeoutError) as error:
            return json_error(400, str(error) or "the video could not be started")
        self.audit.write(request["peer"], "screen", f"video {body.get('preset', 'medium')}" + (" with sound" if started["sound"] else ""))
        return web.json_response({"ok": True, **started})

    async def h_rtc_close(self, request):
        session = (await read_json(request)).get("id")
        return web.json_response({"ok": self._media is not None and await self._media.close(session)})

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
        await self._read_input(ws, await self._region(request))
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

            async def finished():
                code = await process.wait()
                self.events.add("alert", "Finished" if code == 0 else f"Ended with an error ({code})", command[:200])

            asyncio.ensure_future(finished())
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
        if isinstance(data.get("text"), str):
            self._clip_from_phone = data["text"]   # not to be told back to the phone as news
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

    # Bluetooth, displays, sound devices, services, power and the windows.

    async def h_machine(self, request):
        what = request.match_info["what"]
        if what not in machine.READ:
            return json_error(404, "nothing by that name")
        switch = machine.SWITCH.get(what, (None, "allow_input"))[0]
        if switch and not self._allowed(switch):
            return json_error(403, "that is turned off on the computer")
        return web.json_response(await asyncio.to_thread(machine.READ[what]))

    async def h_machine_action(self, request):
        what = request.match_info["what"]
        if what not in machine.ACT:
            return json_error(404, "nothing by that name")
        if not self._allowed(machine.SWITCH.get(what, (None, "allow_input"))[1]):
            return json_error(403, "that is turned off on the computer")
        body = await read_json(request)
        action, target, value = (str(body.get(key, ""))[:200] for key in ("action", "target", "value"))
        done, text = await asyncio.to_thread(machine.ACT[what], action, target, value)
        self.audit.write(request["peer"], what, f"{action} {target} {value}".strip() + ("" if done else f" - {text}"))
        return web.json_response({"ok": done, "text" if done else "error": text})

    async def h_service_log(self, request):
        if not self._allowed("allow_exec"):
            return json_error(403, "commands are turned off on the computer")
        done, text = await asyncio.to_thread(machine.service_log, request.query.get("name", ""))
        return web.json_response({"ok": done, "text": text})

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
        kind = request.query.get("to", "")
        project = ""
        if kind == "scans":
            project = next((p["path"] for p in await asyncio.to_thread(system.projects) if p["active"]), "")
        target = desktop.upload_target(request.query.get("name"), desktop.upload_folder(kind, project))
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

    async def h_open_url(self, request):
        """A web address shared from the phone, opened in the computer's browser."""
        if not self._allowed("allow_input"):
            return json_error(403, "the computer is view-only")
        url = desktop.web_address((await read_json(request)).get("url"))
        if not url:
            return json_error(400, "not a web address")
        self.audit.write(request["peer"], "open-url", url)
        return web.json_response({"ok": await asyncio.to_thread(desktop.open_url, url)})

    async def h_log(self, _request):
        return web.json_response({"entries": self.audit.tail(100)})

    async def h_events(self, request):
        """The computer's notifications and alerts, as they happen.

        ?after=<id> first sends what was said since then, so a phone that was
        out of reach misses nothing that is still remembered. Without a
        socket (?once=1) the same list comes back as one answer.
        """
        def may(kind):
            # Looked at each time, so a switch turned off takes effect on
            # what is already being listened to.
            return kind in EVENT_KINDS and (EVENT_KINDS[kind] is None or self._allowed(EVENT_KINDS[kind]))

        wanted = {kind for kind in request.query.get("kinds", "notification,alert").split(",") if may(kind)}
        try:
            after = int(request.query.get("after", "0"))
        except ValueError:
            after = 0
        missed = [item for item in self.events.since(after) if item["kind"] in wanted]
        if request.query.get("once"):
            return web.json_response({"events": missed})
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=4 * 1024)
        await ws.prepare(request)
        self._track(ws)
        queue = self.events.listen(wanted)
        # A phone that says it is here, and is on the computer's own network
        # (not reaching in from elsewhere), counts as present.
        caller = request["phone"]
        present = request.query.get("present") == "1" and not identity.is_loopback(request["peer"])
        if present:
            self.presence.arrive(caller["fingerprint"], request["peer"])
            if self.presence.locked_here:
                asyncio.ensure_future(self._offer_unlock())
        try:
            for item in missed:
                await ws.send_json(item)
            closing = asyncio.ensure_future(ws.receive())   # nothing is expected; it ends when the phone goes
            while not ws.closed:
                waiting = asyncio.ensure_future(queue.get())
                done, _pending = await asyncio.wait({waiting, closing}, return_when=asyncio.FIRST_COMPLETED)
                if waiting not in done:
                    waiting.cancel()
                    break
                item = waiting.result()
                if may(item["kind"]):
                    await ws.send_json(item)
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            self.events.leave(queue)
            if present:
                self.presence.leave(caller["fingerprint"])
        return ws

    # ------------------------------------------ the phone and the computer

    async def _phone_gone(self):
        """No paired phone is on the network any more."""
        if not self.config["proximity_lock"] or await asyncio.to_thread(desktop.locked):
            return
        if await asyncio.to_thread(desktop.power, "lock"):
            self.presence.locked_here = True
            self.audit.write("-", "locked", "the phone left the network")

    async def _offer_unlock(self):
        """The phone is back and the computer was locked for its leaving:
        ask it, and unlock on its fingerprint."""
        if not self.config["allow_power"]:
            return
        answer = await self.approvals.ask("unlock", f"Unlock {socket.gethostname()}?", self.phones)
        if answer["ok"] and self.presence.locked_here:
            self.presence.locked_here = False
            await asyncio.to_thread(desktop.power, "unlock")
            self.audit.write("-", "unlocked", "the phone came back and approved it")

    async def h_approve(self, request):
        if not self._allowed("allow_power"):
            return json_error(403, "power actions are turned off on the computer")
        data = await read_json(request)
        taken = self.approvals.answer(data.get("ask"), data.get("ok") is True, data.get("signature", ""), request["phone"])
        self.audit.write(request["peer"], "approval", "yes" if data.get("ok") is True else "no")
        return web.json_response({"ok": taken})

    async def h_phone_state(self, request):
        kept = self.phonebook.set_state(request["phone"]["fingerprint"], await read_json(request))
        return web.json_response({"ok": True, **kept})

    async def h_phone_sms(self, request):
        data = await read_json(request)
        entry = self.phonebook.add_message(request["phone"]["name"], data.get("from"), data.get("name"), data.get("text"))
        code = companion.find_code(entry["text"])
        if code and self.config["sync_clipboard"]:
            await asyncio.to_thread(desktop.clipboard_set, code)
        note = entry["text"] + (f"\n\nThe code {code} is on the clipboard." if code and self.config["sync_clipboard"] else "")
        await asyncio.to_thread(self.notifications.show, f"sms:{entry['from']}", "Messages",
                                entry["name"] or entry["from"] or "Text message", note)
        # Who wrote, not what: the message is the owner's, not the log's.
        self.audit.write(request["peer"], "sms", entry["name"] or entry["from"])
        return web.json_response({"ok": True, "code": code})

    async def h_phone_call(self, request):
        data = await read_json(request)
        who = str(data.get("name") or data.get("from") or "Unknown caller")[:60]
        if data.get("state") == "ringing":
            await asyncio.to_thread(self.notifications.show, "call", "Phone", f"{who} is calling",
                                    str(data.get("from") or "")[:40])
            self.audit.write(request["peer"], "call", who)
        else:
            await asyncio.to_thread(self.notifications.dismiss, "call")
        return web.json_response({"ok": True})

    async def h_phone_sent(self, request):
        data = await read_json(request)
        waiting = self._texts.get(str(data.get("id")))
        if waiting is not None and not waiting.done():
            waiting.set_result(data.get("ok") is True)
        return web.json_response({"ok": waiting is not None})

    async def send_text(self, number, text):
        """Ask a listening phone to send a text message. (done, what to say)."""
        number, text = companion.clean_number(number), str(text or "").strip()[:1000]
        if not number or not text:
            return False, "a phone number and something to say"
        if not self.events.listening("sms-send"):
            return False, "no phone is listening (turn on calls and messages in the app)"
        ident = companion.secrets.token_hex(6)
        self._texts[ident] = asyncio.get_running_loop().create_future()
        self.events.add("sms-send", "", keep=False, data={"send": ident, "to": number, "body": text})
        try:
            sent = await asyncio.wait_for(self._texts[ident], 30)
        except asyncio.TimeoutError:
            return False, "the phone did not answer"
        finally:
            self._texts.pop(ident, None)
        self.audit.write("", "sms-sent" if sent else "sms-failed", number)
        return sent, "Sent" if sent else "the phone could not send it"

    async def h_phone_screen(self, request):
        """The phone offers its own screen, to be shown in a window here."""
        body = await read_json(request)
        caller = request["phone"]
        try:
            import phone_screen
            if self._phone_screen is None:
                self._phone_screen = phone_screen.PhoneScreen(
                    relay=self.relay,
                    # What is done in the window goes to the phone it is showing, and to no other.
                    on_input=lambda event: self.events.add("phone-input", "", keep=False, data={"input": event}),
                    on_closed=lambda: self.events.add("cast", "stop", keep=False),
                    show=os.environ.get("ADAPTIVE_LINK_PHONE_WINDOW") != "0")
            self._phone_screen.relay = self.relay
            answer = await asyncio.wait_for(self._phone_screen.answer(body.get("offer"), caller["name"]), 30)
        except ImportError:
            return json_error(503, "video is not installed on the computer (see docs/ADAPTIVE_LINK.md)")
        except (ValueError, asyncio.TimeoutError) as error:
            return json_error(400, str(error) or "the phone's screen could not be shown")
        self.audit.write(request["peer"], "phone-screen", "shown on the computer")
        return web.json_response({"ok": True, "answer": answer})

    async def h_phone_screen_close(self, _request):
        showing = self._phone_screen is not None and self._phone_screen.showing
        if showing:
            await self._phone_screen.close()
        return web.json_response({"ok": showing})

    # ----------------------------------------------- one way in, and scenes

    async def h_ask(self, request):
        """What was asked, as the few things it could mean."""
        text = str((await read_json(request)).get("text", ""))[:300]
        matches = await asyncio.to_thread(self.book.ask, text, self._allowed)
        # A scene asked for by its name is one of the things it could mean.
        for scene in self.scenes.scenes:
            if actions.closeness(text, scene["name"]) >= 0.7:
                matches.insert(0, {"id": "scene", "args": {"name": scene["name"]}, "risk": "changes", "sure": True,
                                   "say": f"Set things as for “{scene['name']}”"})
        return web.json_response({"matches": matches[:actions.MATCHES], "undo": any(e["back"] for e in self.book.journal)})

    async def _do(self, ident, args, who):
        """Do one action, by whoever asked. Returns (done, what to say, how
        long the phone has to keep a change that may have cut it off)."""
        if ident == "scene":
            scene = self.scenes.find(str((args or {}).get("name")))
            if scene is None:
                return False, "no such scene", 0
            said = []
            for step in scene["do"]:
                done, text = await asyncio.to_thread(self.book.run, step["id"], step.get("args", {}), self._allowed)
                if not done:
                    said.append(text)
            self.audit.write(who, "scene", scene["name"])
            return True, scene["name"] + (f" (but: {'; '.join(said)})" if said else ""), 0
        action = self.book.actions().get(ident)
        risky = action is not None and action.risk == "cuts" and ident in ("wifi", "join")
        if risky:
            # The same care as the Network screen takes: undone unless the phone comes back.
            self._hold(None)
            how = ("wifi", args.get("state", "")) if ident == "wifi" else ("join", args.get("network", ""))
            done, text, change = await asyncio.to_thread(system.network_action, *how)
            self.audit.write(who, "do", f"{action.say(args)}" + ("" if done else f" - {text}"))
            return done, text or action.say(args), self._hold(change)
        done, text = await asyncio.to_thread(self.book.run, ident, args, self._allowed)
        said = action.say(args) if action is not None else ident
        self.audit.write(who, "do", said + ("" if done else f" - {text}"))
        return done, text, 0

    async def h_do(self, request):
        body = await read_json(request)
        args = body.get("args") if isinstance(body.get("args"), dict) else {}
        done, text, keep = await self._do(str(body.get("id", ""))[:60], args, request["peer"])
        return web.json_response({"ok": done, "text" if done else "error": text, "keep": keep})

    async def h_actions(self, _request):
        return web.json_response({"actions": await asyncio.to_thread(self.book.catalogue),
                                  "chains": sorted(self.book.chains),
                                  "scenes": [{"name": scene["name"], "auto": scene.get("auto", False)} for scene in self.scenes.scenes],
                                  "recent": [entry["say"] for entry in self.book.journal[-5:]]})

    async def h_chains(self, request):
        """Keep the last few things done as one thing with a name, or forget one."""
        body = await read_json(request)
        if body.get("forget"):
            return web.json_response({"ok": self.book.forget(str(body["forget"]))})
        try:
            done = self.book.remember(body.get("name"), int(body.get("count", 2)))
        except (TypeError, ValueError):
            done = False
        self.audit.write(request["peer"], "chain", str(body.get("name", ""))[:60])
        return web.json_response({"ok": done})

    async def h_watch(self, request):
        """The phone is kept told: it names the parts it is looking at, and
        each is sent when it changes rather than asked for over and over."""
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=8 * 1024)
        await ws.prepare(request)
        self._track(ws)
        wanted, last, due = set(), {}, {}

        async def listen():
            async for message in ws:
                if message.type != WSMsgType.TEXT:
                    continue
                try:
                    named = json.loads(message.data).get("watch", [])
                except (ValueError, AttributeError):
                    continue
                now = {name for name in named if name in WATCHED} if isinstance(named, list) else set()
                for name in now - wanted:
                    last.pop(name, None)   # newly looked at: told at once, changed or not
                    due[name] = 0
                wanted.clear()
                wanted.update(now)

        listening = asyncio.ensure_future(listen())
        try:
            while not ws.closed and not listening.done():
                moment = time.monotonic()
                for name in list(wanted):
                    read, every = WATCHED[name]
                    if moment < due.get(name, 0):
                        continue
                    due[name] = moment + every
                    switch = machine.SWITCH.get(name, (None, None))[0]
                    if switch and not self._allowed(switch):
                        continue
                    try:
                        data = await asyncio.to_thread(read)
                    except Exception:  # noqa: BLE001 - a part that cannot be read now is read again later
                        continue
                    # The same but for the clock is the same: time and traffic counters are not news by themselves.
                    seen = json.dumps({key: value for key, value in data.items() if key not in ("time", "uptime")}
                                      if isinstance(data, dict) else data, sort_keys=True)
                    if seen != last.get(name):
                        last[name] = seen
                        await ws.send_json({"part": name, "data": data})
                await asyncio.sleep(0.5)
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            listening.cancel()
        return ws

    async def h_doctor(self, _request):
        return web.json_response({"checks": await asyncio.to_thread(scenes.doctor, self.describe())})

    async def h_front(self, _request):
        """What is in front on the computer now: for the phone to carry on with."""
        windows = await asyncio.to_thread(machine.windows) if self._allowed("allow_input") else []
        front = next((window for window in windows if window["active"]), None)
        players = await asyncio.to_thread(desktop.players)
        playing = next((player for player in players if player["status"] == "Playing"), None)
        project = next((p for p in await asyncio.to_thread(system.projects) if p["active"]), None)
        return web.json_response({
            "window": {"title": front["title"], "app": front["app"]} if front else None,
            "playing": {key: playing[key] for key in ("title", "artist", "url", "position")} if playing else None,
            "project": {"name": project["name"], "path": project["path"]} if project else None})

    async def _watch_scenes(self):
        """Look at the situation now and then. A scene come round again is
        applied if its owner said to, and otherwise offered to the phone."""
        drives = None
        while True:
            await asyncio.sleep(SCENE_EVERY_S)
            try:
                now = await asyncio.to_thread(scenes.context, self.presence.anyone)
                for scene in self.scenes.entered(now):
                    if scene.get("auto"):
                        await self._do("scene", {"name": scene["name"]}, "-")
                    else:
                        self.events.add("offer", f"{scene['name']}?", "Set things the way you have them there", keep=False,
                                        data={"do": {"id": "scene", "args": {"name": scene["name"]}}})
                # A drive just plugged in, and a chain called "backup": the next step is offered.
                mounted = {drive["mount"]: drive["name"] for drive in await asyncio.to_thread(system.drives)
                           if drive["removable"] and drive["mount"]}
                if drives is not None and "backup" in self.book.chains:
                    for mount in mounted.keys() - drives.keys():
                        self.events.add("offer", f"Back up to {mounted[mount] or mount}?", "Run your backup", keep=False,
                                        data={"do": {"id": "chain", "args": {"name": "backup"}}})
                drives = mounted
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - a look that fails is taken again
                continue

    async def h_mic(self, request):
        """The phone's microphone: 16 kHz, 16-bit, one channel, as it comes."""
        if not self._allowed("allow_input"):
            return json_error(403, "the computer is view-only")
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=256 * 1024)
        microphone = companion.Microphone()
        if not await asyncio.to_thread(microphone.start):
            await asyncio.to_thread(microphone.stop)
            return json_error(503, "the computer has no sound server to give the microphone to")
        await ws.prepare(request)
        self._track(ws)
        self.audit.write(request["peer"], "microphone")
        try:
            async for message in ws:
                if message.type == WSMsgType.BINARY:
                    microphone.push(message.data)
        finally:
            await asyncio.to_thread(microphone.stop)
        return ws

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
        await self._say_nearby(token)
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

    async def _say_nearby(self, token=None):
        """While it waits to be paired with, the computer says on its own
        network that it is here and how to ask (what the QR code holds), so a
        phone on that network can offer it without scanning anything. It
        still pairs only when the owner compares the digits and presses
        Pair. Called with nothing, it stops saying so."""
        if self._nearby is not None:
            try:
                self._nearby.terminate()
            except ProcessLookupError:
                pass
            self._nearby = None
        if token is None or os.environ.get("ADAPTIVE_LINK_NEARBY") == "0":
            return
        try:
            self._nearby = await asyncio.create_subprocess_exec(
                "avahi-publish-service", f"Adaptive Link on {socket.gethostname()}"[:60], "_adaptivelink._tcp",
                str(self.pairing_port), f"n={socket.gethostname()}", f"f={self.fingerprint}", f"t={token}", f"p={self.port}",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        except OSError:
            self._nearby = None   # no avahi here: the code is still there to scan

    async def _close_pairing(self, state):
        await self._say_nearby(None)
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
            try:
                identity.save_phone(pending["name"], pending["cert_pem"], self.link_dir)
            except identity.TooManyPhones as error:
                accept = False
                self.audit.write(pending.get("from", ""), "pairing-refused", str(error))
                desktop.notify("The phone was not paired", str(error).capitalize() + " (link-cli.py unpair NAME).")
            else:
                self.phones = identity.load_phones(self.link_dir)
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

    async def unpair(self, which=None):
        """Forget every paired device, or the one named (or marked by the
        start of its fingerprint)."""
        gone = self.phones
        if which:
            one = identity.find_phone(self.phones, which)
            if one is None:
                return False
            gone = [one]
        removed = identity.forget_phone(self.link_dir, gone[0]["fingerprint"] if which else None)
        self.phones = identity.load_phones(self.link_dir)
        self._decided.clear()
        await self.restart_link()
        if removed:
            self.audit.write("", "unpaired", ", ".join(phone["name"] for phone in gone))
            if self.account is not None and self.account.signed_in:
                for phone in gone:
                    await self._cloud_try(self.account.delete(
                        f"computers/{self.cloud_id}/accepted/{cloud.device_id(phone['fingerprint'])}"))
        return bool(removed)

    async def set_phone_switch(self, which, switch, allowed):
        """Let one device do something, or keep it from it."""
        one = identity.find_phone(self.phones, which)
        if one is None or not identity.deny_phone(one["fingerprint"], switch, not allowed, self.link_dir):
            return False
        # In place, so that what the device has open now follows at once.
        fresh = {phone["fingerprint"]: phone for phone in identity.load_phones(self.link_dir)}
        for phone in self.phones:
            phone["deny"] = fresh.get(phone["fingerprint"], phone)["deny"]
        self.audit.write("", "phone-allowed" if allowed else "phone-denied", f"{one['name']}: {switch}")
        return True

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
                    self.port, report=lambda what: self.audit.write("account", "tunnel-state", what),
                    relay=self.relay)
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
            if any(phone["fingerprint"] == digest for phone in self.phones):
                # Already one of this computer's devices: say so.
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
            "phones": [{"name": phone["name"], "paired_at": phone["paired_at"], "fingerprint": phone["fingerprint"],
                        "deny": phone["deny"], "state": self.phonebook.state.get(phone["fingerprint"])}
                       for phone in self.phones],
            "present": self.presence.anyone,
            "phone_screen": {"showing": self._phone_screen.showing, "frames": self._phone_screen.frames,
                             "size": list(self._phone_screen.size)} if self._phone_screen is not None else None,
            "addresses": [{"address": a, "kind": k} for a, k in addresses],
            "fingerprint": self.fingerprint,
            "viewing": self._sessions + (self._media.viewers if self._media is not None else 0),
            "relay": self.relay["url"] if self.relay else "",
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

        async def unpair(request):
            return web.json_response({"ok": await self.unpair((await read_json(request)).get("phone"))})

        async def phone(request):
            data = await read_json(request)
            done = await self.set_phone_switch(data.get("phone"), f"allow_{data.get('what')}", bool(data.get("allowed")))
            return web.json_response({"ok": done, **self.describe()})

        async def configure(request):
            data = await read_json(request)
            for key in ("allow_input", "allow_exec", "allow_files", "allow_power", "allow_public", "notify_on_connect",
                        "account_enroll", "auto_approve_account", "send_notifications", "sync_clipboard",
                        "proximity_lock"):
                if isinstance(data.get(key), bool):
                    self.config[key] = data[key]
            identity.save_config(self.config, self.link_dir)
            if "account_enroll" in data:
                await self.restart_cloud()
            return web.json_response(self.describe())

        async def wake(request):
            data = await read_json(request)
            if isinstance(data.get("on"), bool):
                done, text = await asyncio.to_thread(system.wake_enable, data["on"])
                return web.json_response({"ok": done, "text": text, **await asyncio.to_thread(system.wake_state)})
            return web.json_response({"ok": True, "addresses": await asyncio.to_thread(system.wake_addresses),
                                      **await asyncio.to_thread(system.wake_state)})

        async def approve(request):
            # Something on this computer wants the phone's yes: sudo, by way
            # of scripts/link-approve.py. The answer carries the phone's
            # signature, which the asker checks for itself.
            data = await read_json(request)
            what = str(data.get("what", ""))[:20]
            if what not in ("sudo", "unlock") or not self.config["allow_power"]:
                return web.json_response({"ok": False, "why": "not something the phone is asked"})
            answer = await self.approvals.ask(what, str(data.get("text", ""))[:200], self.phones, data.get("nonce", ""))
            self.audit.write("", "approval-asked", f"{what}: {'yes' if answer['ok'] else answer.get('why', 'no')}")
            return web.json_response(answer)

        async def ask(request):
            data = await read_json(request)
            allowed = lambda switch: bool(self.config.get(switch))   # noqa: E731 - the owner, at the computer
            if "id" in data:
                done, text, _keep = await self._do(str(data["id"]), data.get("args") or {}, "")
                return web.json_response({"ok": done, "text": text})
            return web.json_response({"matches": await asyncio.to_thread(self.book.ask, str(data.get("text", "")), allowed)})

        async def scene(request):
            data = await read_json(request)
            if data.get("save"):
                now = await asyncio.to_thread(scenes.context, self.presence.anyone)
                kept = self.scenes.save(data["save"], now, await asyncio.to_thread(scenes.arrangement), data.get("auto") is True)
                self.scenes.active.add(kept["name"]) if kept else None
                return web.json_response({"ok": kept is not None, "scene": kept})
            if data.get("forget"):
                return web.json_response({"ok": self.scenes.forget(str(data["forget"]))})
            if data.get("apply"):
                done, text, _keep = await self._do("scene", {"name": str(data["apply"])}, "")
                return web.json_response({"ok": done, "text": text})
            return web.json_response({"ok": True, "scenes": self.scenes.scenes,
                                      "now": await asyncio.to_thread(scenes.context, self.presence.anyone)})

        async def doctor(_request):
            return web.json_response({"checks": await asyncio.to_thread(scenes.doctor, self.describe())})

        async def cast(request):
            # Ask a listening phone to show its screen here (its owner is asked on the phone), or stop one that is.
            data = await read_json(request)
            if data.get("stop"):
                showing = self._phone_screen is not None and self._phone_screen.showing
                if showing:
                    await self._phone_screen.close()
                return web.json_response({"ok": showing})
            if "input" in data:
                # Something to do on the phone, as if done in its window (a script's own tap, or a check's).
                import phone_screen
                event = phone_screen.clean_input(data["input"])
                showing = self._phone_screen is not None and self._phone_screen.showing
                if event and showing:
                    self.events.add("phone-input", "", keep=False, data={"input": event})
                return web.json_response({"ok": bool(event and showing)})
            heard = self.events.listening("cast")
            self.events.add("cast", "start", keep=False)
            return web.json_response({"ok": heard})

        async def ring(_request):
            heard = self.events.listening("ring")
            self.events.add("ring", "", keep=False)
            return web.json_response({"ok": heard})

        async def sms(request):
            data = await read_json(request)
            if data.get("to"):
                done, text = await self.send_text(data.get("to"), data.get("text"))
                return web.json_response({"ok": done, "text": text})
            return web.json_response({"ok": True, "messages": self.phonebook.messages})

        async def relay(request):
            data = await read_json(request)
            if "url" in data:
                kept = identity.save_relay(data if data.get("url") else None, self.link_dir)
                if data.get("url") and kept is None:
                    return web.json_response({"ok": False, "error": "a relay is a TURN server's address: turn:host:3478"})
                self.relay = kept
                if self._tunnel is not None:
                    self._tunnel.relay = kept
                self.audit.write("", "relay", kept["url"] if kept else "none")
            return web.json_response({"ok": True, "relay": self.relay["url"] if self.relay else ""})

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
        app.router.add_post("/phone", phone)
        app.router.add_post("/configure", configure)
        app.router.add_get("/log", log)
        app.router.add_post("/wake", wake)
        app.router.add_post("/relay", relay)
        app.router.add_post("/approve", approve)
        app.router.add_post("/ring", ring)
        app.router.add_post("/cast", cast)
        app.router.add_post("/ask", ask)
        app.router.add_post("/scene", scene)
        app.router.add_get("/doctor", doctor)
        app.router.add_post("/sms", sms)
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
