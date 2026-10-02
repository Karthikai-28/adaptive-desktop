"""Adaptive Link - what the owner's paired phone can ask the desktop to do,
apart from pointer and screen: status, media, sound, notifications, the
clipboard, power, applications and files.

Each function does one thing through the service that already owns it
(MPRIS for players, PulseAudio for volume, logind and systemd for power, the
notification daemon for notifications). Nothing here opens a network socket;
the server calls these only after mutual TLS has established that the request
comes from the one phone the owner paired (see identity.py).

The functions that only decide - where an uploaded file may go, what a name
may contain - are pure, and verify-link.py checks them directly.
"""

import json
import os
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path

UPLOAD_DIR = Path.home() / "Downloads" / "Phone"
LIST_LIMIT = 2000


def _run(argv, timeout=5):
    """(ok, stdout). Never raises."""
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return False, ""
    return done.returncode == 0, done.stdout


def _session_bus():
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib
    return Gio, GLib, Gio.bus_get_sync(Gio.BusType.SESSION, None)


def _call(name, path, interface, method, params=None, timeout=1500):
    """One session-bus call; the unpacked reply, or None if it failed."""
    try:
        Gio, _GLib, bus = _session_bus()
        result = bus.call_sync(name, path, interface, method, params, None,
                               Gio.DBusCallFlags.NO_AUTO_START, timeout, None)
        return result.unpack() if result is not None else ()
    except Exception:  # noqa: BLE001 - a service that is not there is an answer
        return None


# ------------------------------------------------------------------ status

def battery(root="/sys/class/power_supply"):
    """{percent, charging} of the first battery, or None."""
    try:
        names = sorted(n for n in os.listdir(root) if n.startswith("BAT"))
    except OSError:
        return None
    for name in names:
        try:
            percent = int(Path(root, name, "capacity").read_text().strip())
            state = Path(root, name, "status").read_text().strip()
        except (OSError, ValueError):
            continue
        return {"percent": percent, "charging": state in ("Charging", "Full")}
    return None


def parse_volume(text):
    """Percent from `pactl get-sink-volume` output, or None."""
    match = re.search(r"(\d+)%", text or "")
    return int(match.group(1)) if match else None


def volume():
    ok, out = _run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"])
    ok_mute, mute = _run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"])
    return {"percent": parse_volume(out) if ok else None,
            "muted": ok_mute and "yes" in mute}


def locked():
    reply = _call("org.gnome.ScreenSaver", "/org/gnome/ScreenSaver", "org.gnome.ScreenSaver", "GetActive")
    return bool(reply and reply[0])


def status():
    project = _call("org.adaptive.ProjectContext", "/org/adaptive/ProjectContext",
                    "org.adaptive.ProjectContext", "GetActiveProject")
    try:
        uptime = int(float(Path("/proc/uptime").read_text().split()[0]))
    except (OSError, ValueError):
        uptime = 0
    return {
        "host": socket.gethostname(),
        "battery": battery(),
        "volume": volume(),
        "locked": locked(),
        "project": project[1] if project and project[0] else "",
        "uptime": uptime,
        "time": int(time.time()),
    }


# ------------------------------------------------------------- sound, media

VOLUME_STEPS = {"up": "+5%", "down": "-5%"}


def set_volume(action):
    """action: "up", "down", "mute", or a number 0-100."""
    if action == "mute":
        return _run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"])[0]
    if action in VOLUME_STEPS:
        return _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", VOLUME_STEPS[action]])[0]
    try:
        percent = max(0, min(100, int(action)))
    except (TypeError, ValueError):
        return False
    return _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{percent}%"])[0]


MPRIS_PREFIX = "org.mpris.MediaPlayer2."
MPRIS_PATH = "/org/mpris/MediaPlayer2"
MPRIS_PLAYER = "org.mpris.MediaPlayer2.Player"
MEDIA_ACTIONS = {"play-pause": "PlayPause", "play": "Play", "pause": "Pause", "stop": "Stop",
                 "next": "Next", "previous": "Previous"}
_PLAYER_ID = re.compile(r"^[A-Za-z0-9_.\-]{1,120}$")


def players():
    """[{id, name, status, title, artist, length, position}] of what is playing."""
    names = _call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListNames")
    found = []
    for name in (names[0] if names else []):
        if not name.startswith(MPRIS_PREFIX):
            continue
        _Gio, GLib, _bus = _session_bus()
        props = _call(name, MPRIS_PATH, "org.freedesktop.DBus.Properties", "GetAll",
                      GLib.Variant("(s)", (MPRIS_PLAYER,)))
        info = props[0] if props else {}
        meta = info.get("Metadata", {})
        artist = meta.get("xesam:artist", "")
        found.append({
            "id": name[len(MPRIS_PREFIX):],
            "name": name[len(MPRIS_PREFIX):].split(".")[0].capitalize(),
            "status": info.get("PlaybackStatus", "Stopped"),
            "title": str(meta.get("xesam:title", "")),
            "artist": ", ".join(artist) if isinstance(artist, (list, tuple)) else str(artist),
            "length": int(meta.get("mpris:length", 0)) // 1_000_000,
            "position": int(info.get("Position", 0)) // 1_000_000,
        })
    # What is playing first: it is what a press of pause is meant for.
    found.sort(key=lambda p: (p["status"] != "Playing", p["name"]))
    return found


def media(action, player="", seconds=0):
    """A transport action, or "seek" by seconds, on a player (default: the
    one playing)."""
    if not player:
        current = players()
        if not current:
            return False
        player = current[0]["id"]
    if not _PLAYER_ID.match(player):
        return False
    name = MPRIS_PREFIX + player
    if action == "seek":
        _Gio, GLib, _bus = _session_bus()
        try:
            offset = int(float(seconds) * 1_000_000)
        except (TypeError, ValueError):
            return False
        return _call(name, MPRIS_PATH, MPRIS_PLAYER, "Seek", GLib.Variant("(x)", (offset,))) is not None
    method = MEDIA_ACTIONS.get(action)
    return bool(method) and _call(name, MPRIS_PATH, MPRIS_PLAYER, method) is not None


# ----------------------------------------------------------- notifications

def clean_line(text, limit):
    """Text from the phone, made safe to hand to the notification daemon:
    printable, markup characters escaped, bounded."""
    cleaned = "".join(ch if ch.isprintable() or ch == "\n" else " " for ch in str(text or ""))
    cleaned = cleaned.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return cleaned.strip()[:limit]


class Notifications:
    """The phone's notifications, shown by the desktop's own notification
    daemon. One desktop notification per phone notification, replaced when
    the phone updates it and closed when the phone dismisses it."""

    MAX_TRACKED = 200

    def __init__(self):
        self._ids = {}

    def show(self, key, app, title, text):
        _Gio, GLib, _bus = _session_bus()
        key = str(key)[:200]
        summary = clean_line(title, 120) or clean_line(app, 60) or "Phone"
        reply = _call(
            "org.freedesktop.Notifications", "/org/freedesktop/Notifications",
            "org.freedesktop.Notifications", "Notify",
            GLib.Variant("(susssasa{sv}i)", (
                clean_line(app, 60) or "Phone", self._ids.get(key, 0), "phone-symbolic",
                summary, clean_line(text, 600), [],
                {"category": GLib.Variant("s", "device")}, -1)))
        if reply:
            if len(self._ids) >= self.MAX_TRACKED and key not in self._ids:
                self._ids.pop(next(iter(self._ids)))
            self._ids[key] = reply[0]
        return bool(reply)

    def dismiss(self, key):
        _Gio, GLib, _bus = _session_bus()
        shown = self._ids.pop(str(key)[:200], 0)
        if not shown:
            return False
        return _call("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                     "org.freedesktop.Notifications", "CloseNotification",
                     GLib.Variant("(u)", (shown,))) is not None


def notify(title, body):
    """A notification from the link itself: a phone connected, pairing."""
    _run(["notify-send", "--app-name=Adaptive Link", "--icon=phone-symbolic", title, body])


# ---------------------------------------------------------------- clipboard

CLIPBOARD_MAX = 200_000


def clipboard_get():
    ok, out = _run(["xclip", "-selection", "clipboard", "-o"], timeout=3)
    return out[:CLIPBOARD_MAX] if ok else ""


def clipboard_set(text):
    if not isinstance(text, str) or len(text) > CLIPBOARD_MAX:
        return False
    try:
        # xclip stays behind to own the selection, so it is not waited on.
        proc = subprocess.Popen(["xclip", "-selection", "clipboard", "-i"], stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
        proc.stdin.write(text.encode())
        proc.stdin.close()
    except OSError:
        return False
    return True


# -------------------------------------------------------------------- power

# The session and power actions the owner can take from the phone, each
# through logind or systemd exactly as the desktop's own menu does.
POWER_ACTIONS = {
    "lock": ["loginctl", "lock-session"],
    "unlock": ["loginctl", "unlock-session"],
    "screen-off": ["xset", "dpms", "force", "off"],
    "suspend": ["systemctl", "suspend"],
    "reboot": ["systemctl", "reboot"],
    "poweroff": ["systemctl", "poweroff"],
}


def power(action):
    argv = POWER_ACTIONS.get(action)
    return bool(argv) and _run(argv, timeout=10)[0]


# --------------------------------------------------------------------- apps

def applications():
    """[{id, name}] of the applications in the app grid."""
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio
    apps = [{"id": app.get_id(), "name": app.get_display_name() or app.get_name()}
            for app in Gio.AppInfo.get_all() if app.should_show() and app.get_id()]
    apps.sort(key=lambda a: a["name"].casefold())
    return apps


def launch(app_id):
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio
    if not isinstance(app_id, str) or "/" in app_id:
        return False
    try:
        info = Gio.DesktopAppInfo.new(app_id)
        return bool(info and info.launch([], None))
    except Exception:  # noqa: BLE001 - PyGObject raises for an app that is not installed
        return False


# -------------------------------------------------------------------- files

def resolve(path):
    """An absolute, normalised path; "~" and empty mean home."""
    return Path(os.path.abspath(os.path.expanduser(str(path or "~"))))


def list_directory(path):
    """{path, parent, entries: [{name, dir, size, mtime}]}; raises OSError."""
    directory = resolve(path)
    entries = []
    with os.scandir(directory) as scan:
        for entry in scan:
            try:
                info = entry.stat()
                is_dir = entry.is_dir()
            except OSError:
                continue
            entries.append({"name": entry.name, "dir": is_dir,
                            "size": 0 if is_dir else info.st_size, "mtime": int(info.st_mtime)})
            if len(entries) >= LIST_LIMIT:
                break
    entries.sort(key=lambda e: (not e["dir"], e["name"].startswith("."), e["name"].casefold()))
    parent = str(directory.parent) if directory.parent != directory else ""
    return {"path": str(directory), "parent": parent, "entries": entries}


def upload_target(name, directory=None):
    """Where a file sent from the phone is saved: under Downloads/Phone, by
    its own name with nothing of a path left in it, never over an existing
    file."""
    directory = Path(directory or UPLOAD_DIR)
    base = os.path.basename(str(name or "").replace("\\", "/")).strip().lstrip(".")
    base = "".join(ch for ch in base if ch.isprintable() and ch not in "/\0")[:180] or "file"
    target = directory / base
    stem, suffix = os.path.splitext(base)
    counter = 1
    while target.exists():
        counter += 1
        target = directory / f"{stem} ({counter}){suffix}"
    return target


def open_path(path):
    """Open a file or folder on the laptop with its default application."""
    target = resolve(path)
    if not target.exists() or not shutil.which("xdg-open"):
        return False
    subprocess.Popen(["xdg-open", str(target)], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def web_address(url):
    """The address if it is one a browser should be given: http or https,
    one line, with a host. Anything else - a file, a script, a command made
    to look like an address - is not."""
    from urllib.parse import urlsplit
    if not isinstance(url, str) or len(url) > 2000 or any(ch.isspace() or not ch.isprintable() for ch in url):
        return ""
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    return url if parts.scheme in ("http", "https") and parts.hostname else ""


def open_url(url):
    """Open a web address in the computer's browser."""
    address = web_address(url)
    if not address or not shutil.which("xdg-open"):
        return False
    subprocess.Popen(["xdg-open", address], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


# -------------------------------------------------------------------- audit

class Audit:
    """One line per thing the phone did, so there is a record to read."""

    MAX_BYTES = 2 * 1024 * 1024
    KEEP_LINES = 5000

    def __init__(self, path):
        self.path = Path(path)

    def _trim(self):
        """Keep the record bounded: the newest lines, when it has grown large.
        Requests from an unpaired device are written here too, so without a
        bound anyone on the network could fill the disk."""
        try:
            if self.path.stat().st_size <= self.MAX_BYTES:
                return
            lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()[-self.KEEP_LINES:]
            # Down to half the limit, so the trim is not repeated on every line.
            kept, size = [], 0
            for line in reversed(lines):
                size += len(line.encode()) + 1
                if size > self.MAX_BYTES // 2:
                    break
                kept.append(line)
            self.path.write_text("\n".join(reversed(kept)) + "\n", encoding="utf-8")
        except OSError:
            pass

    def write(self, peer, action, detail=""):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._trim()
            line = json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "from": peer,
                               "action": action, "detail": str(detail)[:300]})
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def tail(self, count=50):
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()[-count:]
        except OSError:
            return []
        entries = []
        for line in lines:
            try:
                entries.append(json.loads(line))
            except ValueError:
                continue
        return entries
