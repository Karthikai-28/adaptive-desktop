#!/usr/bin/env python3
"""Kinect Studio: a window on what the Kinect sees and senses.

The page is served by the Kinect hub (services/adaptive-air/kinect_hub.py, 127.0.0.1:8792); this
starts the hub's user service if it is not running and shows the page in a WebKit window. The
same page works in any browser at that address. docs/AIR.md.
"""

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

URL = os.environ.get("KINECT_STUDIO_URL", "http://127.0.0.1:8792/")
UNIT = "adaptive-kinect.service"


def hub_up():
    try:
        urllib.request.urlopen(URL + "api/status", timeout=0.5).read()
        return True
    except OSError:
        return False


def start_hub():
    if hub_up():
        return
    known = subprocess.run(["systemctl", "--user", "cat", UNIT], capture_output=True).returncode == 0
    if known:
        subprocess.run(["systemctl", "--user", "start", UNIT], check=False)
    else:
        python = REPO / ".local/air-venv/bin/python"
        subprocess.Popen([str(python if python.exists() else sys.executable),
                          str(REPO / "services/adaptive-air/kinect_hub.py")],
                         start_new_session=True)
    for _ in range(50):
        if hub_up():
            return
        time.sleep(0.1)


def main():
    GLib.set_prgname("kinect-studio")
    start_hub()
    win = Gtk.Window(title="Kinect Studio")
    win.set_default_size(1560, 980)
    win.set_icon_name("camera-web")
    settings = WebKit2.Settings(enable_webgl=True, enable_developer_extras=bool(os.environ.get("STUDIO_DEVTOOLS")),
                                hardware_acceleration_policy=WebKit2.HardwareAccelerationPolicy.ALWAYS)
    view = WebKit2.WebView(settings=settings)
    ground = Gdk.RGBA()
    ground.parse(adaptive_tokens.load().hex("surface.ground"))
    view.set_background_color(ground)
    view.load_uri(URL)
    win.add(view)
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
