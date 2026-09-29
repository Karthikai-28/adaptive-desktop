#!/usr/bin/env python3
"""Share files with a phone on the same Wi-Fi: a QR code to scan, nothing else.

    nearby_share.py FILE [FILE ...]

Serves only the given files, only while this window is open, at an address
with a random token in it, so nothing else on the machine is reachable and an
address seen once stops working the moment the window closes. Folders are
offered as zips made when first asked for. Nothing leaves the local network:
the phone downloads straight from this computer.

A separate process from Files on purpose: an HTTP server needs threads, and
Files' embedded Python never lets threads run (see adaptive_preview.py).
"""

import html
import mimetypes
import os
import secrets
import shutil
import socket
import sys
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from adaptive_files import qr  # noqa: E402

IDLE_LIMIT_S = 30 * 60


def lan_address():
    """This machine's address on the network the default route uses. A UDP
    'connect' picks the interface without sending anything."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        return probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()


class Share:
    def __init__(self, paths):
        self.paths = [os.path.abspath(p) for p in paths if os.path.exists(p)]
        self.token = secrets.token_urlsafe(9)
        self.downloads = 0
        self.zips = {}
        self.zip_dir = tempfile.mkdtemp(prefix="adaptive-share-")
        self.lock = threading.Lock()
        self.on_download = None

    def item(self, index):
        if 0 <= index < len(self.paths):
            return self.paths[index]
        return None

    def file_for(self, index):
        """A path to send for item index; folders become a zip once."""
        path = self.item(index)
        if path is None:
            return None, None
        if not os.path.isdir(path):
            return path, os.path.basename(path)
        with self.lock:
            if index not in self.zips:
                base = os.path.join(self.zip_dir, f"item{index}")
                self.zips[index] = shutil.make_archive(base, "zip", os.path.dirname(path),
                                                       os.path.basename(path))
        return self.zips[index], os.path.basename(path.rstrip("/")) + ".zip"

    def cleanup(self):
        shutil.rmtree(self.zip_dir, ignore_errors=True)


def make_handler(share):
    class Handler(BaseHTTPRequestHandler):
        server_version = "AdaptiveShare"

        def log_message(self, *_args):
            pass

        def _not_found(self):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):
            parts = [p for p in urllib.parse.urlparse(self.path).path.split("/") if p]
            if not parts or parts[0] != share.token:
                return self._not_found()
            if len(parts) == 1:
                return self._index()
            if len(parts) == 2 and parts[1].isdigit():
                return self._send(int(parts[1]))
            return self._not_found()

        def _index(self):
            rows = []
            for index, path in enumerate(share.paths):
                name = os.path.basename(path.rstrip("/"))
                if os.path.isdir(path):
                    size, name = "folder, as .zip", name + ".zip"
                else:
                    size = GLib.format_size(os.path.getsize(path))
                rows.append(
                    f'<a class="row" href="/{share.token}/{index}">'
                    f'<span class="name">{html.escape(name)}</span>'
                    f'<span class="size">{html.escape(size)}</span></a>')
            page = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Shared files</title><style>
body{{margin:0;padding:24px 16px;background:#1C1C1E;color:#F5F5F7;
font:16px -apple-system,system-ui,Inter,sans-serif}}
h1{{font-size:20px;margin:0 0 4px}} p{{color:#98989D;margin:0 0 16px;font-size:14px}}
.row{{display:flex;justify-content:space-between;gap:12px;padding:14px 16px;margin:8px 0;
background:#2C2C2E;border-radius:12px;color:#F5F5F7;text-decoration:none}}
.name{{overflow-wrap:anywhere}} .size{{color:#0A84FF;white-space:nowrap}}
</style></head><body><h1>Shared from {html.escape(socket.gethostname())}</h1>
<p>Tap a file to download it.</p>{''.join(rows)}</body></html>"""
            body = page.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send(self, index):
            path, name = share.file_for(index)
            if path is None:
                return self._not_found()
            size = os.path.getsize(path)
            kind = mimetypes.guess_type(name)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(size))
            self.send_header("Content-Disposition",
                             "attachment; filename*=UTF-8''" + urllib.parse.quote(name))
            self.end_headers()
            try:
                with open(path, "rb") as handle:
                    shutil.copyfileobj(handle, self.wfile, 1024 * 1024)
            except (BrokenPipeError, ConnectionResetError):
                return
            with share.lock:
                share.downloads += 1
            if share.on_download:
                GLib.idle_add(share.on_download, name)

    return Handler


class QrArea(Gtk.DrawingArea):
    def __init__(self, text, size=260):
        super().__init__()
        self.modules = qr.encode(text)
        self.set_size_request(size, size)

    def do_draw(self, cr):
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        quiet = 4
        cells = len(self.modules) + quiet * 2
        scale = min(width, height) / cells
        ox = (width - cells * scale) / 2
        oy = (height - cells * scale) / 2
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(ox, oy, cells * scale, cells * scale)
        cr.fill()
        cr.set_source_rgb(0, 0, 0)
        for y, row in enumerate(self.modules):
            for x, dark in enumerate(row):
                if dark:
                    cr.rectangle(ox + (x + quiet) * scale, oy + (y + quiet) * scale,
                                 scale + 0.3, scale + 0.3)
        cr.fill()
        return False


CSS = b"""
window { background-color: #1C1C1E; color: #F5F5F7; }
.title { font-size: 17px; font-weight: 700; }
.muted { color: #98989D; font-size: 12.5px; }
.url { font-family: "JetBrains Mono", monospace; font-size: 12px; color: #0A84FF; }
.status { color: #30D158; font-size: 12.5px; }
.card { background-color: #FFFFFF; border-radius: 14px; padding: 12px; }
button.stop { background-image: none; background-color: #FF453A; color: white;
              border: none; border-radius: 8px; min-height: 30px; }
button.quiet { background-image: none; background-color: alpha(white, 0.08); color: #F5F5F7;
               border: none; border-radius: 8px; min-height: 30px; }
"""


def main(argv):
    share = Share(argv[1:])
    if not share.paths:
        return 1

    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                             Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    window = Gtk.Window(title="Share to a Nearby Phone")
    window.set_default_size(380, -1)
    window.set_resizable(False)
    window.set_position(Gtk.WindowPosition.CENTER)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.set_border_width(22)
    window.add(box)

    address = lan_address()
    names = [os.path.basename(p.rstrip("/")) for p in share.paths]
    heading = Gtk.Label(label=names[0] if len(names) == 1 else f"{len(names)} items")
    heading.get_style_context().add_class("title")
    heading.set_ellipsize(3)
    box.pack_start(heading, False, False, 0)

    if address is None:
        note = Gtk.Label(label="This computer isn't on a network. Connect to Wi-Fi and try again.")
        note.set_line_wrap(True)
        note.get_style_context().add_class("muted")
        box.pack_start(note, False, False, 0)
        close = Gtk.Button(label="Close")
        close.get_style_context().add_class("quiet")
        close.connect("clicked", lambda *_: window.destroy())
        box.pack_start(close, False, False, 0)
        window.connect("destroy", Gtk.main_quit)
        window.show_all()
        Gtk.main()
        return 1

    server = ThreadingHTTPServer(("0.0.0.0", 0), make_handler(share))
    server.daemon_threads = True
    url = f"http://{address}:{server.server_address[1]}/{share.token}/"
    threading.Thread(target=server.serve_forever, daemon=True).start()

    hint = Gtk.Label(label="Scan with the phone's camera. It must be on the same Wi-Fi.")
    hint.set_line_wrap(True)
    hint.get_style_context().add_class("muted")
    box.pack_start(hint, False, False, 0)

    card = Gtk.Box()
    card.get_style_context().add_class("card")
    card.set_halign(Gtk.Align.CENTER)
    card.pack_start(QrArea(url), False, False, 0)
    box.pack_start(card, False, False, 6)

    link = Gtk.Label(label=url)
    link.set_selectable(True)
    link.set_line_wrap(True)
    link.get_style_context().add_class("url")
    box.pack_start(link, False, False, 0)

    status = Gtk.Label(label="Waiting for the phone…")
    status.get_style_context().add_class("muted")
    box.pack_start(status, False, False, 0)

    idle = {"timer": 0}

    def expire():
        window.destroy()
        return GLib.SOURCE_REMOVE

    def restart_idle():
        if idle["timer"]:
            GLib.source_remove(idle["timer"])
        idle["timer"] = GLib.timeout_add_seconds(IDLE_LIMIT_S, expire)

    def downloaded(name):
        status.set_text(f"Sent {name} · {share.downloads} download(s) so far")
        status.get_style_context().remove_class("muted")
        status.get_style_context().add_class("status")
        restart_idle()
        return GLib.SOURCE_REMOVE

    share.on_download = downloaded
    restart_idle()

    buttons = Gtk.Box(spacing=8)
    buttons.set_homogeneous(True)
    copy = Gtk.Button(label="Copy Link")
    copy.get_style_context().add_class("quiet")
    copy.connect("clicked", lambda *_: Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(url, -1))
    stop = Gtk.Button(label="Stop Sharing")
    stop.get_style_context().add_class("stop")
    stop.connect("clicked", lambda *_: window.destroy())
    buttons.pack_start(copy, True, True, 0)
    buttons.pack_start(stop, True, True, 0)
    box.pack_start(buttons, False, False, 4)

    foot = Gtk.Label(label="Sharing stops when this window closes, or after 30 idle minutes.")
    foot.set_line_wrap(True)
    foot.get_style_context().add_class("muted")
    box.pack_start(foot, False, False, 0)

    def quit_all(*_args):
        server.shutdown()
        share.cleanup()
        Gtk.main_quit()

    window.connect("destroy", quit_all)
    window.show_all()
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
