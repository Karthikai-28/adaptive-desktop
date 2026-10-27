"""The TV over the home network: wake it, open Screen Share, volume, toasts.

LG webOS TVs take commands over a WebSocket on port 3001 (TLS, self-signed)
or 3000. The first connection shows a prompt on the TV; accepting it gives
a client key, kept in prefs, and later connections are silent. Waking from
standby is a Wake-on-LAN packet to the TV's MAC, which needs "Turn on via
Wi-Fi" in the TV's settings.

Nothing here is required for casting: when the TV is not paired or not
reachable, every call quietly does nothing and the cast goes ahead.
"""

import json
import re
import socket
import subprocess
import threading
import time
import urllib.request

import gi

gi.require_version("Soup", "2.4")
from gi.repository import GLib, Soup  # noqa: E402

import prefs as saved  # noqa: E402

PORTS = (("wss", 3001), ("ws", 3000))
SCREEN_SHARE_IDS = ("com.webos.app.miracast",)
PREPARE_LIMIT_S = 25
WAKE_WAIT_S = 20

PERMISSIONS = [
    "LAUNCH", "LAUNCH_WEBAPP", "APP_TO_APP", "CLOSE", "TEST_OPEN", "TEST_PROTECTED",
    "CONTROL_AUDIO", "CONTROL_DISPLAY", "CONTROL_INPUT_JOYSTICK", "CONTROL_INPUT_MEDIA_RECORDING",
    "CONTROL_INPUT_MEDIA_PLAYBACK", "CONTROL_INPUT_TV", "CONTROL_POWER", "READ_APP_STATUS",
    "READ_CURRENT_CHANNEL", "READ_INPUT_DEVICE_LIST", "READ_NETWORK_STATE", "READ_RUNNING_APPS",
    "READ_TV_CHANNEL_LIST", "WRITE_NOTIFICATION_TOAST", "READ_POWER_STATE", "READ_COUNTRY_INFO",
    "CONTROL_INPUT_TEXT", "CONTROL_MOUSE_AND_KEYBOARD", "READ_INSTALLED_APPS", "READ_SETTINGS",
]

REMOTE_BUTTONS = ("UP", "DOWN", "LEFT", "RIGHT", "ENTER", "BACK", "HOME", "MENU", "EXIT",
                  "VOLUMEUP", "VOLUMEDOWN", "MUTE", "PLAY", "PAUSE", "STOP", "REWIND",
                  "FASTFORWARD", "INFO")


# --- finding TVs on the home network ---------------------------------------

def discover(timeout=4):
    """[{"ip", "name", "model"}] for webOS TVs that answer SSDP. Blocking."""
    found = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.5)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    query = ('M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: "ssdp:discover"\r\n'
             'MX: 2\r\nST: urn:schemas-upnp-org:device:MediaRenderer:1\r\n\r\n').encode()
    for _ in range(2):
        sock.sendto(query, ("239.255.255.250", 1900))
    end = time.time() + timeout
    while time.time() < end:
        try:
            data, (ip, _port) = sock.recvfrom(4096)
        except socket.timeout:
            continue
        text = data.decode("utf-8", "replace")
        if "webos" not in text.lower() or ip in found:
            continue
        location = re.search(r"(?im)^location:\s*(\S+)", text)
        name = model = ""
        if location:
            try:
                xml = urllib.request.urlopen(location.group(1), timeout=3).read().decode("utf-8",
                                                                                          "replace")
                name = _tag(xml, "friendlyName")
                model = _tag(xml, "modelName")
            except OSError:
                pass
        found[ip] = {"ip": ip, "name": name or f"LG TV ({ip})", "model": model}
    sock.close()
    return list(found.values())


def _tag(xml, tag):
    match = re.search(rf"<{tag}>([^<]*)</{tag}>", xml)
    return match.group(1).strip() if match else ""


def mac_of(ip):
    out = subprocess.run(["ip", "neigh", "show", ip], capture_output=True, text=True).stdout
    match = re.search(r"lladdr\s+([0-9a-f:]{17})", out)
    return match.group(1) if match else None


def wake(mac):
    """Wake-on-LAN magic packet, broadcast."""
    payload = bytes.fromhex("ff" * 6 + mac.replace(":", "") * 16)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for port in (9, 7):
            sock.sendto(payload, ("255.255.255.255", port))


def reachable(ip, port=3000, timeout=1.0):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def same_tv(lan_name, p2p_name):
    """"[LG] webOS TV UQ7500PSF" over Wi-Fi Direct is "[LG] webOS TV UQ7500PSF" on the LAN."""
    a = re.sub(r"[^a-z0-9]", "", (lan_name or "").lower())
    b = re.sub(r"[^a-z0-9]", "", (p2p_name or "").lower())
    return bool(a) and bool(b) and (a in b or b in a)


# --- the WebSocket ---------------------------------------------------------

class Link:
    """One SSAP connection. Calls answer on the GLib main loop."""

    def __init__(self, ip, key, log=print):
        self.ip = ip
        self.key = key
        self.log = log
        self.session = Soup.Session()
        self.session.props.ssl_strict = False
        self.session.props.timeout = 6
        self.conn = None
        self.next_id = 0
        self.waiting = {}
        self.on_key = None
        self.on_ready = None
        self.on_fail = None
        self.ready = False

    def open(self, on_ready, on_fail, on_key=None):
        self.on_ready, self.on_fail, self.on_key = on_ready, on_fail, on_key
        self._try(0)

    def _try(self, index):
        if index >= len(PORTS):
            self.on_fail("The TV did not answer on the home network")
            return
        scheme, port = PORTS[index]
        message = Soup.Message.new("GET", f"{scheme}://{self.ip}:{port}/")
        self.session.websocket_connect_async(message, None, None, None, self._opened, index)

    def _opened(self, session, result, index):
        try:
            self.conn = session.websocket_connect_finish(result)
        except GLib.Error as error:
            self.log(f"cast: tv {PORTS[index][0]} failed: {error.message}")
            self._try(index + 1)
            return
        self.conn.connect("message", self._on_message)
        self.conn.connect("closed", lambda *_: self._closed())
        payload = {"forcePairing": False, "pairingType": "PROMPT",
                   "manifest": {"manifestVersion": 1, "appVersion": "1.0",
                                "permissions": PERMISSIONS}}
        if self.key:
            payload["client-key"] = self.key
        self._send({"type": "register", "id": "register_0", "payload": payload})

    def _closed(self):
        self.conn = None
        self.ready = False
        for _, (callback, _) in list(self.waiting.items()):
            callback(None)
        self.waiting.clear()

    def close(self):
        if self.conn:
            self.conn.close(1000, None)
        self.conn = None
        self.ready = False

    def _send(self, data):
        if self.conn:
            self.conn.send_text(json.dumps(data))

    def _on_message(self, _conn, _type, message):
        try:
            data = json.loads(message.get_data().decode("utf-8"))
        except ValueError:
            return
        kind, ident, payload = data.get("type"), data.get("id"), data.get("payload") or {}
        if ident == "register_0":
            if kind == "registered":
                self.key = payload.get("client-key", self.key)
                self.ready = True
                if self.on_key:
                    self.on_key(self.key)
                if self.on_ready:
                    self.on_ready(self)
            elif kind == "response" and payload.get("pairingType") == "PROMPT":
                self.log("cast: tv shows the pairing prompt")
            elif kind == "error":
                self.on_fail(f"The TV refused: {data.get('error', 'not allowed')}")
            return
        waiting = self.waiting.pop(ident, None)
        if waiting:
            callback, _uri = waiting
            ok = kind == "response" and payload.get("returnValue", True)
            callback(payload if ok else None)

    def call(self, uri, payload=None, callback=None):
        if not self.ready:
            if callback:
                callback(None)
            return
        self.next_id += 1
        ident = f"c{self.next_id}"
        self.waiting[ident] = (callback or (lambda _p: None), uri)
        self._send({"type": "request", "id": ident, "uri": uri, "payload": payload or {}})

    def button(self, name):
        """A remote-control key, through the TV's pointer input socket."""
        def got(payload):
            path = (payload or {}).get("socketPath")
            if not path:
                return
            message = Soup.Message.new("GET", path)
            self.session.websocket_connect_async(message, None, None, None, pressed, None)

        def pressed(session, result, _data):
            try:
                pointer = session.websocket_connect_finish(result)
            except GLib.Error:
                return
            pointer.send_text(f"type:button\nname:{name}\n\n")
            GLib.timeout_add(300, lambda: pointer.close(1000, None) or GLib.SOURCE_REMOVE)

        self.call("ssap://com.webos.service.networkinput/getPointerInputSocket", None, got)


# --- what the cast asks for ------------------------------------------------

class TvControl:
    """The TV paired with this laptop. prefs["tvs"] maps LAN address -> details."""

    def __init__(self, prefs, log=print):
        self.prefs = prefs
        self.log = log
        self.link = None
        self.ip = None
        self.previous_app = None
        self.screen_share_id = SCREEN_SHARE_IDS[0]

    # pairing ---------------------------------------------------------------

    def paired(self):
        return {ip: tv for ip, tv in self.prefs.get("tvs", {}).items() if tv.get("key")}

    def known_for(self, p2p_name):
        return self._entry_for(p2p_name) is not None

    def _entry_for(self, p2p_name):
        for ip, tv in self.paired().items():
            if not p2p_name or same_tv(tv.get("name"), p2p_name) or tv.get("p2p") == p2p_name:
                return ip
        return None

    def pair(self, on_done):
        """Find the TV on the network and ask it to trust this laptop.

        on_done(ok, text). The TV shows a prompt; this waits up to a minute.
        """
        def found(tvs):
            if not tvs:
                on_done(False, "No LG TV answered on the home network")
                return GLib.SOURCE_REMOVE
            tv = tvs[0]
            link = Link(tv["ip"], None, self.log)
            link.session.props.timeout = 60

            def keyed(key):
                tvs_saved = self.prefs.setdefault("tvs", {})
                tvs_saved[tv["ip"]] = {"name": tv["name"], "model": tv["model"],
                                       "mac": mac_of(tv["ip"]), "key": key}
                saved.save(self.prefs)

            def ready(_link):
                self.link, self.ip = link, tv["ip"]
                self._learn_screen_share()
                on_done(True, f"Paired with {tv['name']}")

            link.open(ready, lambda text: on_done(False, text), keyed)
            return GLib.SOURCE_REMOVE

        threading.Thread(target=lambda: GLib.idle_add(found, discover()), daemon=True).start()

    def forget(self):
        self.prefs["tvs"] = {}
        saved.save(self.prefs)
        if self.link:
            self.link.close()
        self.link = None

    # connection ------------------------------------------------------------

    def connect(self, on_ready, on_fail=None, p2p_name=None, wake_first=False):
        ip = self._entry_for(p2p_name) or next(iter(self.paired()), None)
        if not ip:
            (on_fail or (lambda _t: None))("Not paired with a TV")
            return
        if self.link and self.link.ready and self.ip == ip:
            on_ready(self.link)
            return
        tv = self.prefs["tvs"][ip]

        def go():
            link = Link(ip, tv["key"], self.log)

            def ready(_link):
                self.link, self.ip = link, ip
                on_ready(link)
            link.open(ready, on_fail or (lambda text: self.log(f"cast: tv: {text}")))

        if wake_first and not reachable(ip):
            self._wake_then(ip, tv, go, on_fail)
        else:
            go()

    def _wake_then(self, ip, tv, then, on_fail):
        if not tv.get("mac"):
            (on_fail or (lambda _t: None))("The TV is off and its address is unknown")
            return
        self.log("cast: waking the TV")
        wake(tv["mac"])

        def wait():
            end = time.time() + WAKE_WAIT_S
            while time.time() < end:
                if reachable(ip):
                    GLib.idle_add(lambda: then() or GLib.SOURCE_REMOVE)
                    return
                time.sleep(1)
            GLib.idle_add(lambda: (on_fail or (lambda _t: None))("The TV did not wake up")
                          or GLib.SOURCE_REMOVE)
        threading.Thread(target=wait, daemon=True).start()

    def _learn_screen_share(self):
        def got(payload):
            for point in (payload or {}).get("launchPoints", []):
                title = (point.get("title") or "").lower()
                if "screen share" in title or "miracast" in point.get("id", ""):
                    self.screen_share_id = point["id"]
                    return
        self.link.call("ssap://com.webos.applicationManager/listLaunchPoints", None, got)

    # the cast's own steps --------------------------------------------------

    def prepare(self, p2p_name, done):
        """Wake the TV, remember what it was showing, open Screen Share.

        done() is called once, whatever happens, within PREPARE_LIMIT_S.
        """
        state = {"done": False}

        def finish():
            if not state["done"]:
                state["done"] = True
                done()
            return GLib.SOURCE_REMOVE

        GLib.timeout_add_seconds(PREPARE_LIMIT_S, finish)

        def ready(link):
            self._learn_screen_share()

            def foreground(payload):
                app = (payload or {}).get("appId")
                if app and app not in SCREEN_SHARE_IDS and app != self.screen_share_id:
                    self.previous_app = app
                link.call("ssap://system.notifications/createToast",
                          {"message": f"Casting from {socket.gethostname()}"})
                link.call("ssap://system.launcher/launch", {"id": self.screen_share_id},
                          lambda _p: GLib.timeout_add_seconds(3, finish))
            link.call("ssap://com.webos.applicationManager/getForegroundAppInfo", None, foreground)

        def failed(text):
            self.log(f"cast: tv: {text}")
            finish()

        self.connect(ready, failed, p2p_name, wake_first=True)

    def finish(self):
        """After casting: put the TV back, switch it off, or leave it."""
        mode = self.prefs.get("tv_end", "restore")
        if mode == "nothing":
            return

        def ready(link):
            if mode == "off":
                link.call("ssap://system/turnOff")
            elif self.previous_app:
                link.call("ssap://system.launcher/launch", {"id": self.previous_app})
            self.previous_app = None
        self.connect(ready)

    # controls for the window ----------------------------------------------

    def volume(self, callback):
        self.connect(lambda link: link.call("ssap://audio/getVolume", None, callback),
                     lambda _t: callback(None))

    def set_volume(self, level):
        self.connect(lambda link: link.call("ssap://audio/setVolume", {"volume": int(level)}))

    def set_mute(self, mute):
        self.connect(lambda link: link.call("ssap://audio/setMute", {"mute": bool(mute)}))

    def toast(self, text):
        self.connect(lambda link: link.call("ssap://system.notifications/createToast",
                                            {"message": text}))

    def button(self, name):
        if name in REMOTE_BUTTONS:
            self.connect(lambda link: link.button(name))

    def power_off(self):
        self.connect(lambda link: link.call("ssap://system/turnOff"))

    def power_on(self, done=None):
        self.connect(lambda _link: done and done(True), lambda _t: done and done(False),
                     wake_first=True)

    def open_url(self, url):
        self.connect(lambda link: link.call("ssap://system.launcher/open", {"target": url}))

    def youtube(self, url):
        """Play a YouTube link in the TV's own YouTube app."""
        match = re.search(r"(?:v=|youtu\.be/|shorts/|embed/)([\w-]{11})", url)
        if not match:
            return False
        target = f"https://www.youtube.com/tv?v={match.group(1)}"
        self.connect(lambda link: link.call("ssap://system.launcher/launch",
                                            {"id": "youtube.leanback.v4",
                                             "params": {"contentTarget": target}}))
        return True
