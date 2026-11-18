#!/usr/bin/env python3
"""Kinect: one app for fitness, games, the camera, the room, 3D scanning and your history.

    kinect.py [section] [--fullscreen] [--demo] [--game walls|pose|race]

    section: home (the default), fitness, games, camera, room, scan, history; also the old
             names: arcade (= games) and studio (= camera); fitness/<exercise> opens on one

The page is served by Kinect Motion (services/kinect-motion/server.py, 127.0.0.1:8793), which
reads the Kinect hub; this starts its user service when it is not running and shows the page in
one WebKit window. It is a single-instance application: running it again (or through the old
commands, Kinect Studio's or Kinect Fitness's) brings the open window forward on that section.
F11 toggles full screen (for the TV). --demo runs a private server with two synthetic people
(no Kinect needed). docs/KINECT_MOTION.md.
"""

import argparse
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("WebKit2", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk, WebKit2  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import adaptive_tokens  # noqa: E402

UNIT = "kinect-motion.service"
SECTIONS = ("home", "fitness", "games", "camera", "room", "scan", "history")
ALIASES = {"arcade": "games", "studio": "camera", "motion": "home", "": "home"}


def parse(argv):
    p = argparse.ArgumentParser(prog="kinect.py", description=__doc__.split("\n\n")[0])
    p.add_argument("section", nargs="?", default="home")
    p.add_argument("--fullscreen", action="store_true")
    p.add_argument("--demo", action="store_true", help="two synthetic people, no Kinect")
    p.add_argument("--game", choices=("walls", "pose", "race"), help="Games: open straight into one")
    a = p.parse_args(argv)
    head, _, rest = a.section.partition("/")
    head = ALIASES.get(head, head)
    if head not in SECTIONS:
        p.error(f"section: one of {', '.join(SECTIONS)} (or arcade, studio)")
    a.path = head + (f"/{rest}" if rest else "") + (f"/{a.game}" if a.game and head == "games" else "")
    return a


def base_url(demo):
    return os.environ.get("KINECT_MOTION_URL", "http://127.0.0.1:8798" if demo else "http://127.0.0.1:8793")


def up(base):
    try:
        urllib.request.urlopen(base + "/api/state", timeout=0.5).read()
        return True
    except OSError:
        return False


def start_server(base, demo):
    """Make sure Kinect Motion answers at `base` (its user service, or a private demo server)."""
    if up(base):
        return True
    python = REPO / ".local/air-venv/bin/python"
    server = REPO / "services/kinect-motion/server.py"
    # The server outlives this window, so it must not hold the window's output open.
    quiet = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "start_new_session": True}
    if demo:
        subprocess.Popen([str(python if python.exists() else sys.executable), str(server), "--demo",
                          "--port", base.rsplit(":", 1)[1], "--db", ":memory:"], **quiet)
    elif subprocess.run(["systemctl", "--user", "cat", UNIT], capture_output=True).returncode == 0:
        subprocess.run(["systemctl", "--user", "start", UNIT], check=False)
    else:
        subprocess.Popen([str(python if python.exists() else sys.executable), str(server)], **quiet)
    for _ in range(80):
        if up(base):
            return True
        time.sleep(0.1)
    return False


class App(Gtk.Application):
    def __init__(self, demo):
        super().__init__(application_id="com.karthi.Kinect" + (".Demo" if demo else ""),
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.win = self.view = None
        self.full = False

    def do_command_line(self, cmdline):
        try:
            args = parse(cmdline.get_arguments()[1:])
        except SystemExit:
            return 2
        base = base_url(args.demo)
        if self.win is None:
            if not start_server(base, args.demo):
                print("kinect: Kinect Motion did not start (systemctl --user status kinect-motion)", file=sys.stderr)
            self._window(base)
        self.view.load_uri(f"{base}/app#/{args.path}")
        if args.fullscreen and not self.full:
            self.toggle_full()
        self.win.present_with_time(Gtk.get_current_event_time() or int(GLib.get_monotonic_time() / 1000))
        return 0

    def _window(self, base):
        GLib.set_prgname("kinect")
        self.win = Gtk.ApplicationWindow(application=self, title="Kinect")
        self.win.set_default_size(1760, 1040)
        self.win.set_icon_name("camera-web")
        settings = WebKit2.Settings(enable_webgl=True, enable_fullscreen=True,
                                    enable_developer_extras=bool(os.environ.get("KINECT_DEVTOOLS")),
                                    hardware_acceleration_policy=WebKit2.HardwareAccelerationPolicy.ALWAYS)
        # Nothing kept between runs but the page's own small preferences: the pages are local
        # and the history lives in the service.
        data = GLib.get_user_cache_dir() + "/adaptive-desktop/kinect-web"
        manager = WebKit2.WebsiteDataManager(base_data_directory=data, base_cache_directory=data + "/cache")
        context = WebKit2.WebContext.new_with_website_data_manager(manager)
        context.set_cache_model(WebKit2.CacheModel.DOCUMENT_VIEWER)
        self.view = WebKit2.WebView(settings=settings, web_context=context)
        ground = Gdk.RGBA()
        ground.parse(adaptive_tokens.load().hex("surface.ground"))
        self.view.set_background_color(ground)
        self.win.add(self.view)
        self.win.connect("key-press-event", self._key)
        self.win.show_all()

    def toggle_full(self):
        (self.win.unfullscreen if self.full else self.win.fullscreen)()
        self.full = not self.full

    def _key(self, _w, event):
        if event.keyval == Gdk.KEY_F11:
            self.toggle_full()
            return True
        return False


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    demo = "--demo" in argv
    parse(argv)                       # errors before a window opens
    return App(demo).run([sys.argv[0], *argv])


if __name__ == "__main__":
    sys.exit(main())
