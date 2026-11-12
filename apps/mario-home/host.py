#!/usr/bin/env python3
"""Show Mario Hub's pages on the desktop: Home as the desktop layer, the panel on a key.

    host.py            Home: a desktop-type window over the primary monitor's work area, under
                       every other window and on every workspace (started at login, Adaptive
                       session only)
    host.py --panel    the Mario panel: a window at the right edge, above the others; running it
                       again while it is open closes it (Super+J)

Both load http://127.0.0.1:<port>/ from Mario Hub and retry until it answers. GTK 3 + WebKitGTK
(gir1.2-webkit2-4.1, or 4.0), as on Ubuntu 22.04; X11, where GNOME 42 honours the desktop hint.
"""
import json
import os
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
for _v in ("4.1", "4.0"):
    try:
        gi.require_version("WebKit2", _v)
        break
    except ValueError:
        continue
from gi.repository import Gdk, Gio, GLib, Gtk, WebKit2  # noqa: E402

CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "adaptive-desktop" / "mario.json"
PANEL_W = 760


def hub_url(path="/"):
    try:
        port = int(json.loads(CONFIG.read_text()).get("port", 8791))
    except (OSError, ValueError, TypeError):
        port = 8791
    return f"http://127.0.0.1:{port}{path}"


def make_view(path):
    settings = WebKit2.Settings(enable_developer_extras=bool(os.environ.get("MARIO_DEVTOOLS")),
                                enable_write_console_messages_to_stdout=True,
                                hardware_acceleration_policy=WebKit2.HardwareAccelerationPolicy.ON_DEMAND)
    view = WebKit2.WebView(settings=settings)
    view.set_background_color(Gdk.RGBA(0.078, 0.078, 0.086, 1))
    if not os.environ.get("MARIO_DEVTOOLS"):
        view.connect("context-menu", lambda *_: True)

    def retry(*_):
        GLib.timeout_add_seconds(2, lambda: (view.load_uri(hub_url(path)), False)[1])
        return True

    def stay_inside(_view, decision, kind):
        # links that leave the hub open in the browser, not inside the desktop
        if kind == WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            uri = decision.get_navigation_action().get_request().get_uri()
            if not uri.startswith(hub_url("")):
                Gio.AppInfo.launch_default_for_uri(uri, None)
                decision.ignore()
                return True
        return False

    view.connect("load-failed", retry)
    view.connect("decide-policy", stay_inside)
    view.load_uri(hub_url(path))
    return view


def workarea():
    display = Gdk.Display.get_default()
    monitor = display.get_primary_monitor() or display.get_monitor(0)
    return monitor.get_workarea()


class Home(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="com.karthi.MarioHome", flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.win = None

    def do_activate(self):
        if self.win:
            return
        win = Gtk.ApplicationWindow(application=self, title="Mario Home")
        win.set_type_hint(Gdk.WindowTypeHint.DESKTOP)
        win.set_decorated(False)
        win.set_skip_taskbar_hint(True)
        win.set_skip_pager_hint(True)
        win.set_keep_below(True)
        win.set_focus_on_map(False)   # appearing at login never takes focus from an app
        win.stick()

        def place(*_):
            area = workarea()
            win.move(area.x, area.y)
            win.resize(area.width, area.height)

        # The shell's dock hides for fullscreen or maximized windows and the top bar treats them
        # as covering the screen. Home is neither: it fills the work area (which leaves out the top
        # bar and the rail; the page keeps the floating dock's band free) and stays a plain desktop
        # layer, so the dock, the top bar and everything on them keep working exactly as without it.
        def stay_plain(_win, event):
            state = event.new_window_state
            if state & Gdk.WindowState.FULLSCREEN:
                win.unfullscreen()
            if state & Gdk.WindowState.MAXIMIZED:
                win.unmaximize()
                GLib.idle_add(lambda: (place(), False)[1])
            return False

        win.connect("window-state-event", stay_plain)
        place()
        Gdk.Screen.get_default().connect("monitors-changed", place)
        win.add(make_view("/"))
        win.show_all()
        self.win = win


class Panel(Gtk.Application):
    """Unique per session: a second launch reaches the first, which toggles."""

    def __init__(self):
        super().__init__(application_id="com.karthi.MarioPanel", flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.win = None

    def do_activate(self):
        if self.win and self.win.get_visible():
            self.win.hide()
            return
        if not self.win:
            win = Gtk.ApplicationWindow(application=self, title="Mario")
            win.set_type_hint(Gdk.WindowTypeHint.DIALOG)
            win.set_keep_above(True)
            win.set_skip_taskbar_hint(True)
            win.connect("delete-event", lambda w, _e: (w.hide(), True)[1])
            win.connect("key-press-event", lambda w, e: (w.hide(), True)[1] if e.keyval == Gdk.KEY_Escape else False)
            win.add(make_view("/panel"))
            self.win = win
        area = workarea()
        self.win.resize(PANEL_W, area.height - 32)
        self.win.move(area.x + area.width - PANEL_W - 16, area.y + 16)
        self.win.show_all()
        self.win.present_with_time(Gtk.get_current_event_time() or GLib.get_monotonic_time() // 1000)


def main():
    panel = "--panel" in sys.argv[1:]
    # The autostart entry is seen by the normal Ubuntu session too, which must stay as it was:
    # Home only covers the desktop inside the Adaptive session (its wrapper sets this profile).
    if not panel and os.environ.get("DCONF_PROFILE") != "adaptive" and not os.environ.get("MARIO_ANY_SESSION"):
        print("Mario Home runs in the Adaptive Desktop session only (MARIO_ANY_SESSION=1 overrides).")
        return 0
    app = Panel() if panel else Home()
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
