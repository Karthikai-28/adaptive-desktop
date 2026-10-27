#!/usr/bin/env python3
"""Cast - show this laptop on a TV over Miracast (Wi-Fi Direct), and more.

One running copy owns the cast; later invocations hand it their command, so
the keyboard shortcut, the palette, Files and the phone all drive the same
cast as the window.

  main.py                      the window
  main.py --toggle             cast to the last TV, or stop if casting
  main.py --cast NAME          cast to the TV whose name contains NAME
  main.py --stop               stop casting
  main.py --freeze / --curtain [TEXT] / --resume
  main.py --show screen|window|left|right   what to send (window: the focused one)
  main.py --set KEY=VALUE      change an option (quality, sound, cursor, clock, ...)
  main.py --play FILE          play a video, song or photo on the TV (no mirroring)
  main.py --youtube URL        open a YouTube link in the TV's own app
  main.py --wall               show the wall page (clock, weather, vitals) on the TV
  main.py --status             print the current cast state as JSON

Debugging, without the running copy:
  main.py --list               print the TVs found in ten seconds
  main.py --connect NAME [--seconds N]
"""

import argparse
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import controller  # noqa: E402
import p2p  # noqa: E402
import stream  # noqa: E402

APP_ID = controller.APP_ID
HERE = Path(__file__).resolve().parent
# How long a command waits for the TV to show up before giving up.
FIND_WAIT_S = 20


def parser():
    p = argparse.ArgumentParser(prog="cast", description=__doc__.splitlines()[0])
    p.add_argument("--toggle", action="store_true")
    p.add_argument("--cast", metavar="NAME")
    p.add_argument("--stop", action="store_true")
    p.add_argument("--freeze", action="store_true")
    p.add_argument("--curtain", nargs="?", const="", metavar="TEXT")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--show", choices=("screen", "window", "left", "right"))
    p.add_argument("--set", metavar="KEY=VALUE", action="append", default=[])
    p.add_argument("--play", metavar="FILE")
    p.add_argument("--youtube", metavar="URL")
    p.add_argument("--wall", action="store_true")
    p.add_argument("--status", action="store_true")
    p.add_argument("--list", action="store_true")
    p.add_argument("--connect", metavar="NAME")
    p.add_argument("--seconds", type=int, default=0)
    return p


# --- debugging paths (no running copy) -------------------------------------

def run_list():
    loop = GLib.MainLoop()
    link = p2p.WifiDirect(lambda _d: None, lambda *_: None)
    if not link.ready:
        print("No Wi-Fi Direct device.")
        return 1
    link.start_find()

    def done():
        link.stop_find()
        for d in link.displays():
            state = "ready" if d.available else "busy"
            print(f"{d.name}\t{d.address}\t{d.strength}%\t{state}")
        loop.quit()
    GLib.timeout_add_seconds(10, done)
    loop.run()
    return 0


def run_connect(name, seconds):
    missing = stream.missing_elements()
    if missing:
        print("Install first: sudo apt install " + " ".join(missing))
        return 1
    loop = GLib.MainLoop()
    result = {"code": 1}
    picked = []
    cast = None

    def on_state(state, text):
        print(f"[{state}] {text}", flush=True)
        if state == "streaming":
            result["code"] = 0
            if seconds:
                GLib.timeout_add_seconds(seconds, lambda: cast.stop() or GLib.SOURCE_REMOVE)
        if state in ("ended", "failed"):
            GLib.timeout_add(800, loop.quit)

    def on_displays(displays):
        if picked:
            return
        for d in displays:
            if name.lower() in d.name.lower():
                print(f"Found {d.name} ({d.address})", flush=True)
                picked.append(d)
                cast.start(d)
                return

    cast = controller.Cast(on_state, on_displays)
    if not cast.link.ready:
        print("No Wi-Fi Direct device.")
        return 1
    cast.link.start_find()
    on_displays(cast.link.displays())
    GLib.timeout_add_seconds(30, lambda: (picked or (print("TV not found"), loop.quit()))
                             and GLib.SOURCE_REMOVE)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, 2, lambda: cast.stop() or GLib.SOURCE_REMOVE)
    loop.run()
    return result["code"]


def parse_value(text):
    lowered = text.strip().lower()
    if lowered in ("true", "on", "yes"):
        return True
    if lowered in ("false", "off", "no"):
        return False
    return text


def source_for(name):
    """A source dict for --show. "window" is whichever window has focus now."""
    import subprocess
    import desk
    width, height = desk.screen_size()
    half = width // 2 // 2 * 2
    if name == "window":
        out = subprocess.run(["xdotool", "getactivewindow"], capture_output=True, text=True)
        xid = int(out.stdout.strip() or 0)
        title = next((w["title"] for w in desk.windows() if w["xid"] == xid), "Window")
        if xid:
            return {"kind": "window", "xid": xid, "title": title[:60]}
    if name == "left":
        return {"kind": "region", "x": 0, "y": 0, "w": half, "h": height, "title": "Left half"}
    if name == "right":
        return {"kind": "region", "x": width - half, "y": 0, "w": half, "h": height,
                "title": "Right half"}
    return {"kind": "screen"}


# --- the running copy --------------------------------------------------------

class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.cast = None
        self.window = None
        self.media = None
        self.held = False
        self.pending = None
        self.listeners = []

    # the cast is created once, on first use -----------------------------

    def ensure_cast(self):
        if self.cast is None:
            self.cast = controller.Cast(self._on_state, self._on_displays, preview=True)
            self.cast.link.start_find()
        return self.cast

    def _on_state(self, state, text):
        if state == "streaming" and not self.held:
            # Casting continues with the window closed.
            self.hold()
            self.held = True
        if state in ("ended", "failed", "idle") and self.held:
            self.release()
            self.held = False
        for listener in list(self.listeners):
            listener.on_state(state, text)

    def _on_displays(self, displays):
        if self.pending and self.pending(displays):
            self.pending = None
        for listener in list(self.listeners):
            listener.on_displays(displays)

    # commands -----------------------------------------------------------

    def do_command_line(self, command_line):
        try:
            args = parser().parse_args(command_line.get_arguments()[1:])
        except SystemExit:
            return 2
        if args.status:
            data = controller.STATE_FILE.read_text() if controller.STATE_FILE.exists() else "{}"
            command_line.print_literal(data + "\n")
            return 0
        cast = self.ensure_cast()
        if args.toggle:
            if cast.casting:
                cast.stop()
            else:
                self.cast_to(None)
        elif args.cast:
            self.cast_to(args.cast)
        elif args.stop:
            cast.stop()
        elif args.freeze:
            cast.freeze(True)
        elif args.curtain is not None:
            cast.set_curtain(args.curtain)
        elif args.resume:
            cast.freeze(False)
            cast.set_curtain(None)
        elif args.show:
            cast.set_source(source_for(args.show))
        elif args.set:
            for item in args.set:
                key, _, value = item.partition("=")
                if key in controller.saved.DEFAULTS:
                    cast.set_option(key, parse_value(value))
        elif args.play:
            self.play_file(args.play)
        elif args.youtube:
            self.ensure_cast().tv.youtube(args.youtube)
        elif args.wall:
            self.show_wall()
        else:
            self.present_window()
        return 0

    def do_activate(self):
        self.present_window()

    def present_window(self):
        if self.window is None:
            import window as cast_window
            # The palette is dark; ask the theme for its dark widgets to match.
            Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)
            css = Gtk.CssProvider()
            css.load_from_path(str(HERE / "style.css"))
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            self.window = cast_window.Window(self)
            self.window.connect("close-request", self._window_closed)
        self.window.present()

    def _window_closed(self, window):
        if window in self.listeners:
            self.listeners.remove(window)
        self.window = None
        return False

    def cast_to(self, wanted):
        """Cast to a TV by name (None: the last one), waiting for it to be found."""
        cast = self.ensure_cast()

        def look(_displays):
            display = cast.find_display(wanted)
            if display:
                cast.start(display)
                return True
            return False

        if not look(None):
            self.hold()
            self.pending = look
            name = wanted or (cast.prefs.get("last_display") or {}).get("name") or "the TV"
            for listener in list(self.listeners):
                listener.on_state("preparing", f"Looking for {name}")

            def give_up():
                if self.pending is look:
                    self.pending = None
                    for listener in list(self.listeners):
                        listener.on_state("failed", f"{name} was not found nearby")
                self.release()
                return GLib.SOURCE_REMOVE
            GLib.timeout_add_seconds(FIND_WAIT_S, give_up)

    def media_server(self):
        import media
        tvs = self.ensure_cast().tv.paired()
        if not tvs:
            return None, None
        ip = next(iter(tvs))
        if self.media is None:
            self.media = media.Server(ip, lambda: self.cast.prefs.get("wall_place"))
            self.media.start()
        return self.media, ip

    def play_file(self, path, done=None):
        import threading
        import media
        server, ip = self.media_server()
        if not server:
            if done:
                done(False, "Pair with the TV first (TV tab)")
            return
        self.hold()

        def work():
            try:
                media.play_file(server, path, ip)
                result = (True, f"Playing {Path(path).name} on the TV")
            except OSError as error:
                result = (False, f"The TV could not play it: {error}")
            GLib.idle_add(lambda: (done and done(*result)) or GLib.SOURCE_REMOVE)
        threading.Thread(target=work, daemon=True).start()

    def show_wall(self):
        server, _ip = self.media_server()
        if server:
            self.hold()
            self.ensure_cast().tv.open_url(server.wall_url())


def main():
    args, _rest = parser().parse_known_args()
    if args.list:
        return run_list()
    if args.connect:
        return run_connect(args.connect, args.seconds)
    GLib.set_prgname(APP_ID)
    GLib.set_application_name("Cast")
    return App().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
