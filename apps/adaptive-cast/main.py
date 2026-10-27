#!/usr/bin/env python3
"""Cast - show this laptop's screen on a TV over Miracast (Wi-Fi Direct).

The window lists TVs that answer Wi-Fi Direct and say they can show a
Wi-Fi Display stream. Pick one and the laptop joins its group, the TV
opens the RTSP session, and the desktop (with its sound) is sent as
H.264 + AAC in MPEG-TS over RTP. The home Wi-Fi stays connected.

  main.py                       the window
  main.py --list                print the TVs found in ten seconds
  main.py --connect NAME        cast to the first TV whose name contains NAME
"""

import argparse
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p2p  # noqa: E402
import session as cast_session  # noqa: E402

APP_ID = "com.karthi.AdaptiveCast"
HERE = Path(__file__).resolve().parent
OPEN_TIMEOUT_S = 30
# A TV that has just ended a session drops the next join for a few seconds.
RETRY_AFTER_S = 6


class Cast:
    """Ties the Wi-Fi Direct link to the RTSP session; either ending ends both.

    on_state(state, text) gets: idle, connecting, negotiating, streaming,
    ended, failed.
    """

    def __init__(self, on_state, on_displays, log=print):
        self.on_state = on_state
        self.log = log
        self.link = p2p.WifiDirect(on_displays, self._on_link, log)
        self.session = None
        self.wait_timer = 0
        self.display = None
        self.retried = False

    def start(self, display, retry=False):
        self.stop()
        self.retried = retry
        self.display = display
        self.session = cast_session.Session(self._on_session, self.log)
        try:
            self.session.listen()
        except GLib.Error as error:
            self.session = None
            self.on_state("failed", f"Port 7236 is busy: {error.message}")
            return
        self.link.connect_to(display)

    def stop(self):
        self._clear_wait()
        if self.session:
            session, self.session = self.session, None
            session.stop()
        # The link closing after this was asked for; it is not news.
        self.display = None
        self.link.disconnect()

    def _clear_wait(self):
        if self.wait_timer:
            GLib.source_remove(self.wait_timer)
            self.wait_timer = 0

    def _on_link(self, state, text):
        self.log(f"cast: link {state}: {text}")
        if state == "connecting":
            self.on_state("connecting", text)
        elif state == "connected":
            self.on_state("connecting", "Linked. Waiting for the TV to open the session")
            self.wait_timer = GLib.timeout_add_seconds(OPEN_TIMEOUT_S, self._open_timeout)
        elif state in ("disconnected", "failed"):
            if self.display is None:
                return
            display, self.display = self.display, None
            self._clear_wait()
            if (state == "disconnected" and not self.retried and self.session
                    and self.session.state == "listening"):
                self.on_state("connecting", "The TV is still busy. Trying again")
                session, self.session = self.session, None
                session.on_state = lambda *_: None
                session.stop()
                self.display = display
                GLib.timeout_add_seconds(RETRY_AFTER_S, self._retry, display)
                return
            if self.session:
                session, self.session = self.session, None
                # Reported below; the session's own "ended" would repeat it.
                session.on_state = lambda *_: None
                session.stop(text)
            self.on_state("failed" if state == "failed" else "ended", text)

    def _retry(self, display):
        if self.display is display and self.session is None:
            self.start(display, retry=True)
        return GLib.SOURCE_REMOVE

    def _open_timeout(self):
        self.wait_timer = 0
        if self.session and self.session.state == "listening":
            self.stop()
            self.on_state("failed", "The TV linked but never opened the session. "
                                    "Open Screen Share on the TV and try again.")
        return GLib.SOURCE_REMOVE

    def _on_session(self, state, text):
        if state == "listening":
            return
        if state in ("negotiating", "streaming"):
            self._clear_wait()
        if state in ("ended", "failed") and self.session:
            self.session = None
            self.display = None
            self.link.disconnect()
        self.on_state(state, text)


# --- command line ----------------------------------------------------------

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
    missing = cast_session.missing_elements()
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

    cast = Cast(on_state, on_displays)
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


# --- window ----------------------------------------------------------------

class Window(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Cast")
        self.set_default_size(440, 520)
        self.add_css_class("adaptive-cast")
        self.cast = Cast(self._on_state, self._on_displays)
        self.casting = None

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.add_css_class("root")
        self.set_child(root)

        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        header.add_css_class("header")
        title = Gtk.Label(label="Cast to a TV", xalign=0)
        title.add_css_class("title")
        hint = Gtk.Label(label="Wireless display over Wi-Fi Direct. Your Wi-Fi stays connected.",
                         xalign=0, wrap=True)
        hint.add_css_class("muted")
        header.append(title)
        header.append(hint)
        root.append(header)

        self.banner = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.banner.add_css_class("banner")
        root.append(self.banner)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.add_css_class("displays")
        scroller = Gtk.ScrolledWindow(vexpand=True, child=self.list)
        root.append(scroller)

        footer = Gtk.Box(spacing=12)
        footer.add_css_class("footer")
        self.spinner = Gtk.Spinner()
        self.status = Gtk.Label(xalign=0, hexpand=True, wrap=True)
        self.status.add_css_class("status")
        self.stop_button = Gtk.Button(label="Stop casting", visible=False)
        self.stop_button.add_css_class("stop")
        self.stop_button.connect("clicked", lambda *_: self.cast.stop())
        footer.append(self.spinner)
        footer.append(self.status)
        footer.append(self.stop_button)
        root.append(footer)

        missing = cast_session.missing_elements()
        if not self.cast.link.ready:
            self._banner("This laptop has no Wi-Fi Direct device, so it cannot cast.")
        elif missing:
            self._banner("Needs a video encoder first. In a terminal:\n"
                         "sudo apt install " + " ".join(missing))
        else:
            self.banner.set_visible(False)

        self._on_displays(self.cast.link.displays())
        self.cast.link.start_find()
        self._idle("Looking for TVs nearby")
        self.connect("close-request", self._on_close)

    def _banner(self, text):
        self.banner.set_label(text)
        self.banner.set_visible(True)

    def _idle(self, text):
        self.spinner.start()
        self.status.set_label(text)

    def _on_displays(self, displays):
        while (row := self.list.get_row_at_index(0)) is not None:
            self.list.remove(row)
        if not displays:
            empty = Gtk.Label(label="No TVs yet. Turn on Screen Share (LG) or Screen Mirroring "
                                    "on the TV.", wrap=True)
            empty.add_css_class("muted")
            empty.add_css_class("empty")
            self.list.append(empty)
            return
        blocked = bool(self.banner.get_visible())
        for display in displays:
            row = Gtk.Box(spacing=12)
            row.add_css_class("display")
            icon = Gtk.Image.new_from_icon_name("video-display-symbolic")
            icon.set_pixel_size(28)
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
            name = Gtk.Label(label=display.name, xalign=0, ellipsize=Pango.EllipsizeMode.END)
            name.add_css_class("name")
            detail = Gtk.Label(xalign=0, label=f"{'Ready' if display.available else 'Busy'}"
                                               f" · signal {display.strength}%")
            detail.add_css_class("muted")
            text.append(name)
            text.append(detail)
            button = Gtk.Button(label="Cast")
            button.add_css_class("cast")
            button.set_sensitive(not blocked and self.casting is None)
            button.connect("clicked", self._on_cast, display)
            row.append(icon)
            row.append(text)
            row.append(button)
            self.list.append(row)

    def _on_cast(self, _button, display):
        self.casting = display
        self.cast.start(display)
        self._on_displays(self.cast.link.displays())

    def _on_state(self, state, text):
        self.status.set_label(text)
        self.stop_button.set_visible(state in ("connecting", "negotiating", "streaming"))
        if state == "streaming":
            self.spinner.stop()
        elif state in ("ended", "failed"):
            self.casting = None
            self.status.remove_css_class("live")
            if state == "failed":
                self.status.add_css_class("error")
            self.cast.link.start_find()
            self._on_displays(self.cast.link.displays())
            self.spinner.start()
        else:
            self.status.remove_css_class("error")
            self.spinner.start()
        if state == "streaming":
            self.status.add_css_class("live")

    def _on_close(self, *_):
        self.cast.link.stop_find()
        self.cast.stop()
        return False


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        window = self.get_active_window()
        if window is None:
            css = Gtk.CssProvider()
            css.load_from_path(str(HERE / "style.css"))
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            window = Window(self)
        window.present()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list", action="store_true", help="print TVs found nearby")
    parser.add_argument("--connect", metavar="NAME", help="cast to the TV whose name contains NAME")
    parser.add_argument("--seconds", type=int, default=0, help="with --connect: stop after this long")
    args = parser.parse_args()
    if args.list:
        return run_list()
    if args.connect:
        return run_connect(args.connect, args.seconds)
    return App().run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
