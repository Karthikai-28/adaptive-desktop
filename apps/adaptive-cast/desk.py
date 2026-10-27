"""The desktop around a cast: pointer, windows, sleep and notifications.

The pointer is read straight from X (it is asked for on every frame, from
the streaming thread, so it uses its own X connection). Window lists come
from wmctrl, polled on the main loop. Everything that changes a desktop
setting records the old value in a state file first, so a crash mid-cast is
undone the next time Cast starts.
"""

import ctypes
import ctypes.util
import json
import os
import re
import subprocess
import threading
from pathlib import Path

from gi.repository import Gio, GLib

STATE = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "adaptive-cast-restore.json"


# --- X pointer -------------------------------------------------------------

class _X:
    _lib = None

    @classmethod
    def lib(cls):
        if cls._lib is None:
            lib = ctypes.cdll.LoadLibrary(ctypes.util.find_library("X11") or "libX11.so.6")
            lib.XOpenDisplay.restype = ctypes.c_void_p
            lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
            lib.XDefaultRootWindow.restype = ctypes.c_ulong
            lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
            u, i, ui = ctypes.c_ulong, ctypes.c_int, ctypes.c_uint
            lib.XQueryPointer.argtypes = [ctypes.c_void_p, u, ctypes.POINTER(u), ctypes.POINTER(u),
                                          ctypes.POINTER(i), ctypes.POINTER(i), ctypes.POINTER(i),
                                          ctypes.POINTER(i), ctypes.POINTER(ui)]
            lib.XTranslateCoordinates.argtypes = [ctypes.c_void_p, u, u, i, i, ctypes.POINTER(i),
                                                  ctypes.POINTER(i), ctypes.POINTER(u)]
            lib.XSetErrorHandler.argtypes = [ctypes.c_void_p]
            lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
            cls._lib = lib
            # A window that closes mid-query must not abort the process.
            cls._handler = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)(
                lambda *_: 0)
            lib.XSetErrorHandler(cls._handler)
        return cls._lib


class Pointer:
    """Where the mouse is, and whether a button is down.

    One X connection per OS thread. Not threading.local: GStreamer calls in
    from its own threads, and Python gives each such callback a fresh thread
    state, so thread-local data would be lost (and a connection leaked) on
    every frame until X refuses new clients.
    """

    def __init__(self):
        self._displays = {}
        self._lock = threading.Lock()

    def _display(self):
        ident = threading.get_native_id()
        with self._lock:
            entry = self._displays.get(ident)
            if entry is None:
                lib = _X.lib()
                d = lib.XOpenDisplay(None)
                entry = (d, lib.XDefaultRootWindow(d) if d else 0)
                self._displays[ident] = entry
        self._root = entry[1]
        return entry[0]

    def close(self):
        lib = _X.lib() if self._displays else None
        with self._lock:
            for d, _root in self._displays.values():
                if d:
                    lib.XCloseDisplay(d)
            self._displays.clear()

    def position(self):
        """(x, y, pressed) in root coordinates, or None without X."""
        d = self._display()
        if not d:
            return None
        lib = _X.lib()
        root, child = ctypes.c_ulong(), ctypes.c_ulong()
        rx, ry, wx, wy = ctypes.c_int(), ctypes.c_int(), ctypes.c_int(), ctypes.c_int()
        mask = ctypes.c_uint()
        if not lib.XQueryPointer(d, self._root, ctypes.byref(root), ctypes.byref(child),
                                 ctypes.byref(rx), ctypes.byref(ry), ctypes.byref(wx),
                                 ctypes.byref(wy), ctypes.byref(mask)):
            return None
        # Button1Mask is 1 << 8.
        return rx.value, ry.value, bool(mask.value & (1 << 8))

    def window_origin(self, xid):
        """Root coordinates of a window's top-left corner."""
        d = self._display()
        if not d:
            return 0, 0
        lib = _X.lib()
        x, y, child = ctypes.c_int(), ctypes.c_int(), ctypes.c_ulong()
        lib.XTranslateCoordinates(d, xid, self._root, 0, 0, ctypes.byref(x),
                                  ctypes.byref(y), ctypes.byref(child))
        return x.value, y.value


# --- windows ---------------------------------------------------------------

def _run(*args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def current_desktop():
    for line in _run("wmctrl", "-d").splitlines():
        parts = line.split()
        if len(parts) > 1 and parts[1] == "*":
            return int(parts[0])
    return 0


def windows():
    """Normal windows on any desktop: dicts with xid, cls, title, x, y, w, h, desktop."""
    out = []
    for line in _run("wmctrl", "-lGx").splitlines():
        parts = line.split(None, 8)
        if len(parts) < 8:
            continue
        xid, desktop, x, y, w, h, cls = parts[:7]
        title = parts[8] if len(parts) > 8 else ""
        if desktop == "-1" or cls in ("gjs.Gjs", "N/A"):
            continue
        out.append({"xid": int(xid, 16), "cls": cls, "title": title, "x": int(x), "y": int(y),
                    "w": int(w), "h": int(h), "desktop": int(desktop)})
    return out


def minimized(xid):
    return "_NET_WM_STATE_HIDDEN" in _run("xprop", "-id", hex(xid), "_NET_WM_STATE")


def matches(cls, title, patterns):
    text = f"{cls} {title}".lower()
    return any(p.strip().lower() in text for p in patterns if p.strip())


def sensitive_rects(patterns):
    """Screen rectangles of visible windows matching any pattern."""
    here = current_desktop()
    rects = []
    for win in windows():
        if win["desktop"] != here or not matches(win["cls"], win["title"], patterns):
            continue
        if minimized(win["xid"]):
            continue
        rects.append((win["x"], win["y"], win["w"], win["h"]))
    return rects


def screen_size():
    out = _run("xdpyinfo")
    match = re.search(r"dimensions:\s+(\d+)x(\d+)", out)
    if match:
        return int(match.group(1)), int(match.group(2))
    return 1920, 1080


# --- crash-safe restore ----------------------------------------------------

def _remember(key, value):
    data = {}
    try:
        data = json.loads(STATE.read_text())
    except (OSError, ValueError):
        pass
    if value is None:
        data.pop(key, None)
    else:
        data[key] = value
    if data:
        STATE.write_text(json.dumps(data))
    else:
        STATE.unlink(missing_ok=True)


def pending_restore():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


# --- quiet notifications ---------------------------------------------------

NOTIFY_SCHEMA = "org.gnome.desktop.notifications"


class QuietNotifications:
    """Hide notification banners while casting; the old value comes back after."""

    def __init__(self):
        self.settings = Gio.Settings.new(NOTIFY_SCHEMA)
        self.was = None

    def start(self):
        if self.was is not None:
            return
        self.was = self.settings.get_boolean("show-banners")
        _remember("show-banners", self.was)
        self.settings.set_boolean("show-banners", False)

    def stop(self):
        if self.was is None:
            return
        self.settings.set_boolean("show-banners", self.was)
        self.was = None
        _remember("show-banners", None)
        Gio.Settings.sync()

    @staticmethod
    def recover():
        was = pending_restore().get("show-banners")
        if was is not None:
            Gio.Settings.new(NOTIFY_SCHEMA).set_boolean("show-banners", was)
            _remember("show-banners", None)
            Gio.Settings.sync()


# --- stay awake ------------------------------------------------------------

class StayAwake:
    """GNOME session inhibitor: no suspend and no screen blank while casting."""

    SUSPEND, IDLE = 4, 8

    def __init__(self, app_id):
        self.app_id = app_id
        self.cookie = None

    def start(self, reason="Casting to a TV"):
        if self.cookie is not None:
            return
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            reply = bus.call_sync(
                "org.gnome.SessionManager", "/org/gnome/SessionManager",
                "org.gnome.SessionManager", "Inhibit",
                GLib.Variant("(susu)", (self.app_id, 0, reason, self.SUSPEND | self.IDLE)),
                GLib.VariantType("(u)"), Gio.DBusCallFlags.NONE, 3000, None)
            self.cookie = reply.unpack()[0]
        except GLib.Error:
            self.cookie = None

    def stop(self):
        if self.cookie is None:
            return
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            bus.call_sync("org.gnome.SessionManager", "/org/gnome/SessionManager",
                          "org.gnome.SessionManager", "Uninhibit", GLib.Variant("(u)", (self.cookie,)),
                          None, Gio.DBusCallFlags.NONE, 3000, None)
        except GLib.Error:
            pass
        self.cookie = None
