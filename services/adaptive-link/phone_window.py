#!/usr/bin/env python3
"""Adaptive Link - the window the phone's screen is shown in.

Started by the daemon (phone_screen.py) with the phone's name. Pictures
arrive on standard input - width and height, then that many pixels - and
what is done in the window leaves on standard output, a line of JSON each:

    {"t": "tap", "x": 0.5, "y": 0.5}            places are fractions of the picture
    {"t": "swipe", "x": .., "y": .., "x2": .., "y2": .., "ms": 250}
    {"t": "hold", "x": .., "y": ..}
    {"t": "key", "k": "back"}
    {"t": "text", "s": "hello"}

Closing the window ends it, and with it the phone's sending.
"""

import json
import struct
import sys
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

HOLD_S = 0.6
MOVED = 0.02   # further than this, as a fraction of the picture, a press is a swipe


def say(event):
    sys.stdout.write(json.dumps(event) + "\n")
    sys.stdout.flush()


class Window(Gtk.ApplicationWindow):
    def __init__(self, app, name):
        super().__init__(application=app, title=name)
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)
        self.size = (0, 0)
        self.sized = False
        self._down = None

        bar = Gtk.HeaderBar()
        for label, key, tip in (("◀", "back", "Back"), ("●", "home", "Home"), ("■", "recents", "Recent apps")):
            button = Gtk.Button(label=label, tooltip_text=tip)
            button.connect("clicked", lambda _button, key=key: say({"t": "key", "k": key}))
            bar.pack_start(button)
        self.set_titlebar(bar)

        # Fitted whole, keeping its shape (what GTK does by default; said in the
        # way GTK 4.6, which Ubuntu 22.04 has, understands).
        self.picture = Gtk.Picture(can_shrink=True, keep_aspect_ratio=True)
        self.picture.set_hexpand(True)
        self.picture.set_vexpand(True)
        self.set_child(self.picture)
        self.set_default_size(420, 880)

        press = Gtk.GestureDrag()
        press.connect("drag-begin", self.pressed)
        press.connect("drag-end", self.released)
        self.picture.add_controller(press)
        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self.scrolled)
        self.picture.add_controller(scroll)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.typed)
        self.add_controller(keys)

    def place(self, x, y):
        """Where in the phone's picture a point of the widget is, 0 to 1 each
        way, or None outside it (the picture is fitted, with bars beside it)."""
        width, height = self.picture.get_width(), self.picture.get_height()
        if not self.size[0] or not width or not height:
            return None
        scale = min(width / self.size[0], height / self.size[1])
        shown_w, shown_h = self.size[0] * scale, self.size[1] * scale
        fx, fy = (x - (width - shown_w) / 2) / shown_w, (y - (height - shown_h) / 2) / shown_h
        return (min(1.0, max(0.0, fx)), min(1.0, max(0.0, fy))) if -0.02 <= fx <= 1.02 and -0.02 <= fy <= 1.02 else None

    def pressed(self, _gesture, x, y):
        at = self.place(x, y)
        self._down = (at, time.monotonic(), x, y) if at else None

    def released(self, _gesture, dx, dy):
        if not self._down:
            return
        start, when, x, y = self._down
        self._down = None
        end = self.place(x + dx, y + dy) or start
        held = time.monotonic() - when
        if abs(end[0] - start[0]) > MOVED or abs(end[1] - start[1]) > MOVED:
            say({"t": "swipe", "x": start[0], "y": start[1], "x2": end[0], "y2": end[1], "ms": int(max(80, min(1500, held * 1000)))})
        elif held >= HOLD_S:
            say({"t": "hold", "x": start[0], "y": start[1]})
        else:
            say({"t": "tap", "x": start[0], "y": start[1]})

    def scrolled(self, _controller, _dx, dy):
        # The wheel is a short swipe up or down the middle of the screen.
        if dy:
            say({"t": "swipe", "x": 0.5, "y": 0.5, "x2": 0.5, "y2": 0.5 - 0.25 * (1 if dy > 0 else -1), "ms": 120})
        return True

    def typed(self, _controller, keyval, _keycode, _state):
        if keyval == Gdk.KEY_Escape:
            say({"t": "key", "k": "back"})
            return True
        character = Gdk.keyval_to_unicode(keyval)
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            say({"t": "text", "s": "\n"})
        elif keyval == Gdk.KEY_BackSpace:
            say({"t": "text", "s": "\b"})
        elif character and chr(character).isprintable():
            say({"t": "text", "s": chr(character)})
        else:
            return False
        return True

    def show_picture(self, width, height, data):
        self.size = (width, height)
        if not self.sized:
            # The window takes the phone's shape, at a size that fits a screen.
            self.sized = True
            tall = min(880, height)
            self.set_default_size(max(240, int(tall * width / height)), tall)
        texture = Gdk.MemoryTexture.new(width, height, Gdk.MemoryFormat.R8G8B8, GLib.Bytes.new(data), width * 3)
        self.picture.set_paintable(texture)
        return False


def read(window, app):
    """Pictures from the daemon, until it stops sending."""
    source = sys.stdin.buffer
    while True:
        head = source.read(8)
        if len(head) < 8:
            break
        width, height = struct.unpack("<II", head)
        if not 0 < width <= 4096 or not 0 < height <= 4096:
            break
        data = source.read(width * height * 3)
        if len(data) < width * height * 3:
            break
        GLib.idle_add(window.show_picture, width, height, data)
    GLib.idle_add(app.quit)


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "Phone"
    # Not one-of-a-kind: each phone shown has a window, and none waits on the session bus to open.
    app = Gtk.Application(application_id="com.karthi.AdaptiveLinkPhone", flags=Gio.ApplicationFlags.NON_UNIQUE)

    def activate(app):
        window = Window(app, name)
        window.present()
        threading.Thread(target=read, args=(window, app), daemon=True).start()

    app.connect("activate", activate)
    app.run(None)


if __name__ == "__main__":
    main()
