#!/usr/bin/env python3
"""Adaptive Link - pair a phone.

Shows the QR code the Adaptive Link app scans. When a phone answers, the
window shows its name and six digits; the same six digits are on the phone.
Nothing is trusted until Pair is pressed here, on the computer.

Closing the window, or two minutes passing, ends the attempt.
"""

import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "extension"))
import control  # noqa: E402
from adaptive_files import qr  # noqa: E402 - the same encoder the Files share dialog uses

APP_ID = "com.karthi.AdaptiveLinkPair"

CSS = b"""
window.pair { background-color: #1C1C1E; color: #F5F5F7; font-family: Inter, sans-serif; }
.pair-box { padding: 22px 26px; }
.pair-title { font-size: 18px; font-weight: 700; }
.pair-muted { color: #98989D; font-size: 13px; }
.pair-code { font-size: 34px; font-weight: 700; letter-spacing: 4px; }
.pair-card { background-color: #FFFFFF; border-radius: 14px; padding: 12px; }
button.pair-primary { background: none; background-color: #0A84FF; color: white; border: none;
                      border-radius: 9px; min-height: 34px; padding: 0 18px; }
button.pair-quiet { background: none; background-color: alpha(white, 0.08); color: #F5F5F7;
                    border: none; border-radius: 9px; min-height: 34px; padding: 0 18px; }
"""


class PairWindow(Gtk.ApplicationWindow):
    def __init__(self, app, attach=False):
        super().__init__(application=app, title="Pair a phone")
        # Attached: opened by the daemon because a phone has asked to pair in
        # a pairing this window did not start. It shows the request and must
        # not start, or on closing cancel, a pairing of its own.
        self.attached = attach
        self.add_css_class("pair")
        self.set_resizable(False)
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.modules = []
        self.state = "idle"
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.box.add_css_class("pair-box")
        self.set_child(self.box)
        self.connect("close-request", self._on_close)

        if attach:
            self.hosts = []
            self._message("A phone is asking to pair", "One moment\u2026")
            GLib.timeout_add(200, self._poll)
            return

        try:
            started = control.call("POST", "/pair/start", {"ui": True})
        except control.NotRunning:
            self._message("Adaptive Link is not running",
                          "Start it with: systemctl --user start adaptive-link")
            return
        self.modules = qr.encode(started["payload"])
        self.text_code = started.get("text", "")
        self.hosts = started["hosts"]
        self._show_code()
        GLib.timeout_add(500, self._poll)

    # -------------------------------------------------------------- pages

    def _clear(self):
        child = self.box.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            self.box.remove(child)
            child = following

    def _label(self, text, css, wrap=True):
        label = Gtk.Label(label=text, xalign=0.5, wrap=wrap, justify=Gtk.Justification.CENTER)
        label.add_css_class(css)
        label.set_max_width_chars(46)
        return label

    def _message(self, title, detail):
        self._clear()
        self.box.append(self._label(title, "pair-title"))
        self.box.append(self._label(detail, "pair-muted"))
        close = Gtk.Button(label="Close", halign=Gtk.Align.CENTER)
        close.add_css_class("pair-quiet")
        close.connect("clicked", lambda _b: self.close())
        self.box.append(close)

    def _show_code(self):
        self._clear()
        self.box.append(self._label("Pair your phone", "pair-title"))
        self.box.append(self._label("Open Adaptive Link on the phone and scan this code.", "pair-muted"))
        card = Gtk.Box(halign=Gtk.Align.CENTER)
        card.add_css_class("pair-card")
        area = Gtk.DrawingArea(content_width=300, content_height=300)
        area.set_draw_func(self._draw)
        card.append(area)
        self.box.append(card)
        where = ", ".join(self.hosts) if self.hosts else "no network address found"
        self.box.append(self._label(f"This computer: {where}", "pair-muted"))
        self.remaining = self._label("", "pair-muted")
        self.box.append(self.remaining)
        if self.text_code:
            # For a phone that cannot scan: the same code, to type or paste.
            copy = Gtk.Button(label="Copy the code as text", halign=Gtk.Align.CENTER)
            copy.add_css_class("pair-quiet")
            copy.connect("clicked", self._copy_text)
            self.box.append(copy)

    def _show_request(self, name, code, account="", device=""):
        self._clear()
        self.box.append(self._label(f"{name} wants to pair", "pair-title"))
        if account:
            # The request came through the account's own space, which only a
            # device signed in to that account can write to.
            self.box.append(self._label(f"Signed in as {account}, the same Google account as this computer.",
                                        "pair-muted"))
        self.box.append(self._label("Check that the phone shows the same six digits.", "pair-muted"))
        self.box.append(self._label(f"{code[:3]} {code[3:]}", "pair-code", wrap=False))
        self.box.append(self._label(
            "Pairing gives this phone full control of the computer: its screen, keyboard, "
            "files and commands. Only pair a phone that is yours.", "pair-muted"))
        row = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER)
        reject = Gtk.Button(label="Reject")
        reject.add_css_class("pair-quiet")
        reject.connect("clicked", lambda _b: self._decide(False))
        accept = Gtk.Button(label="Pair")
        accept.add_css_class("pair-primary")
        accept.connect("clicked", lambda _b: self._decide(True))
        row.append(reject)
        row.append(accept)
        self.box.append(row)

    def _copy_text(self, button):
        Gdk.Display.get_default().get_clipboard().set_content(
            Gdk.ContentProvider.new_for_value(self.text_code))
        button.set_label("Copied")

    def _draw(self, _area, cr, width, height):
        quiet = 4
        cells = len(self.modules) + quiet * 2
        scale = min(width, height) / cells
        cr.set_source_rgb(1, 1, 1)
        cr.paint()
        cr.set_source_rgb(0, 0, 0)
        for y, line in enumerate(self.modules):
            for x, dark in enumerate(line):
                if dark:
                    cr.rectangle((x + quiet) * scale, (y + quiet) * scale, scale + 0.3, scale + 0.3)
        cr.fill()

    # -------------------------------------------------------------- state

    def _poll(self):
        try:
            state = control.call("GET", "/pair/state")
        except control.NotRunning:
            self._message("Adaptive Link stopped", "Pairing was not completed.")
            return GLib.SOURCE_REMOVE

        current = state.get("state")
        if current == "waiting":
            if not self.attached:
                self.remaining.set_text(f"Waiting for the phone - {state.get('seconds_left', 0)} s left")
        elif current == "pending" and self.state != "pending":
            self._show_request(state["name"], state["code"], state.get("account", ""), state.get("device", ""))
        elif current == "paired":
            self.state = current
            self._message("Paired", "The phone can now connect to this computer.")
            return GLib.SOURCE_REMOVE
        elif current == "rejected":
            self.state = current
            self._message("Not paired", "The phone was rejected.")
            return GLib.SOURCE_REMOVE
        elif current in ("expired", "idle"):
            self.state = current
            self._message("Pairing ended", "No phone was paired. Open this window again to retry.")
            return GLib.SOURCE_REMOVE
        self.state = current
        return GLib.SOURCE_CONTINUE

    def _decide(self, accept):
        try:
            control.call("POST", "/pair/decide", {"accept": accept})
        except control.NotRunning:
            pass

    def _on_close(self, *_):
        if self.attached:
            # Closing the request without answering it is a "no".
            if self.state == "pending":
                self._decide(False)
            return False
        if self.state in ("waiting", "pending", "idle"):
            try:
                control.call("POST", "/pair/cancel")
            except control.NotRunning:
                pass
        return False


def main():
    attach = "--attach" in sys.argv
    # Not unique when attached: the request has to appear even if a pairing
    # window from an earlier attempt was left open.
    app = Gtk.Application(application_id=APP_ID + (".Request" if attach else ""))
    app.connect("activate", lambda a: (a.get_active_window() or PairWindow(a, attach)).present())
    return app.run(None)


if __name__ == "__main__":
    GLib.set_prgname(APP_ID)
    sys.exit(main())
