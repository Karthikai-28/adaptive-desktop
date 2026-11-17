#!/usr/bin/env python3
"""Kinect Fitness, Kinect Arcade and Kinect Room as windows.

    motion.py fitness | arcade | room [--fullscreen] [--demo]

The pages are served by Kinect Motion (services/kinect-motion/server.py, 127.0.0.1:8793); this
starts its user service when it is not running and shows the page in a WebKit window. F11 toggles
full screen (for the TV). The same pages work in any browser at that address. --demo runs a
private server with two synthetic people (no Kinect needed). docs/KINECT_MOTION.md.
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
from gi.repository import Gdk, GLib, Gtk, WebKit2  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import adaptive_tokens  # noqa: E402

UNIT = "kinect-motion.service"
TITLES = {"fitness": "Kinect Fitness", "arcade": "Kinect Arcade", "room": "Kinect Room"}


def up(base):
    try:
        urllib.request.urlopen(base + "/api/state", timeout=0.5).read()
        return True
    except OSError:
        return False


def start(base, demo):
    """Make sure the server answers at `base`."""
    if up(base):
        return
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
    for _ in range(60):
        if up(base):
            return
        time.sleep(0.1)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("page", nargs="?", default="fitness", choices=sorted(TITLES))
    parser.add_argument("--fullscreen", action="store_true")
    parser.add_argument("--demo", action="store_true", help="two synthetic people, no Kinect")
    parser.add_argument("--game", choices=("walls", "pose", "race"), help="Arcade: open straight into a game")
    args = parser.parse_args()
    base = os.environ.get("KINECT_MOTION_URL", "http://127.0.0.1:8798" if args.demo else "http://127.0.0.1:8793")
    GLib.set_prgname(f"kinect-{args.page}")
    start(base, args.demo)
    win = Gtk.Window(title=TITLES[args.page])
    win.set_default_size(1600, 960)
    win.set_icon_name({"fitness": "applications-games", "arcade": "input-gaming", "room": "user-home"}[args.page])
    settings = WebKit2.Settings(enable_developer_extras=bool(os.environ.get("MOTION_DEVTOOLS")),
                                hardware_acceleration_policy=WebKit2.HardwareAccelerationPolicy.ALWAYS)
    # Nothing kept between runs: the pages are local, and the history lives in the service.
    context = WebKit2.WebContext.new_with_website_data_manager(WebKit2.WebsiteDataManager.new_ephemeral())
    view = WebKit2.WebView(settings=settings, web_context=context)
    ground = Gdk.RGBA()
    ground.parse(adaptive_tokens.load().hex("surface.ground"))
    view.set_background_color(ground)
    view.load_uri(f"{base}/{args.page}" + (f"?game={args.game}" if args.game else ""))
    win.add(view)
    full = {"on": False}

    def key(_w, event):
        if event.keyval == Gdk.KEY_F11:
            (win.unfullscreen if full["on"] else win.fullscreen)()
            full["on"] = not full["on"]
            return True
        return False

    win.connect("key-press-event", key)
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    if args.fullscreen:
        win.fullscreen()
        full["on"] = True
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
