"""Play things on the TV without mirroring, and the wall display.

  play_file   serve a local file over HTTP and hand its URL to the TV's DLNA
              renderer: the TV decodes at full quality, the laptop stays free
  Wall        a page for the TV's browser: clock, date, weather and this
              laptop's vitals, for when nothing is being cast

The HTTP server listens only on the address this laptop uses to reach the
TV, and serves only what was shared, under a random token.
"""

import html
import json
import mimetypes
import os
import re
import secrets
import socket
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlencode

AVT = "urn:schemas-upnp-org:service:AVTransport:1"
HERE = Path(__file__).resolve().parent


def local_ip_towards(ip):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect((ip, 9))
        return sock.getsockname()[0]


def parse_range(header, size):
    """'bytes=START-END' -> (start, end) inclusive, or None for the whole file."""
    match = re.match(r"bytes=(\d*)-(\d*)$", header or "")
    if not match or size == 0:
        return None
    start, end = match.groups()
    if start == "":
        length = int(end or 0)
        return max(0, size - length), size - 1
    start = int(start)
    end = min(int(end), size - 1) if end else size - 1
    if start > end:
        return None
    return start, end


# WMO weather codes, grouped the way a glance needs them.
WEATHER_TEXT = {0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Cloudy", 45: "Fog",
                48: "Fog", 51: "Drizzle", 53: "Drizzle", 55: "Drizzle", 61: "Rain", 63: "Rain",
                65: "Heavy rain", 71: "Snow", 73: "Snow", 75: "Snow", 80: "Showers", 81: "Showers",
                82: "Heavy showers", 95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm"}
_weather_cache = {"at": 0, "key": None, "value": None}


def geocode(city):
    """{"name", "lat", "lon"} for a place name (Open-Meteo, no key). Blocking."""
    url = "https://geocoding-api.open-meteo.com/v1/search?" + urlencode({"name": city, "count": 1})
    with urllib.request.urlopen(url, timeout=6) as reply:
        results = json.loads(reply.read()).get("results") or []
    if not results:
        return None
    top = results[0]
    return {"name": top["name"], "lat": top["latitude"], "lon": top["longitude"]}


def weather(place):
    """Current weather for a geocoded place, cached for ten minutes."""
    if not place:
        return None
    key = (place["lat"], place["lon"])
    if _weather_cache["key"] == key and time.time() - _weather_cache["at"] < 600:
        return _weather_cache["value"]
    url = ("https://api.open-meteo.com/v1/forecast?" +
           urlencode({"latitude": place["lat"], "longitude": place["lon"],
                      "current_weather": "true"}))
    try:
        with urllib.request.urlopen(url, timeout=6) as reply:
            now = json.loads(reply.read())["current_weather"]
        value = {"temperature": now["temperature"], "place": place["name"],
                 "text": WEATHER_TEXT.get(int(now["weathercode"]), "")}
    except (OSError, KeyError, ValueError):
        value = None
    _weather_cache.update(at=time.time(), key=key, value=value)
    return value


def vitals(place=None):
    """CPU, memory, battery and weather for the wall page."""
    out = {"host": socket.gethostname(), "time": time.time(), "weather": weather(place)}
    try:
        load = os.getloadavg()[0]
        out["cpu"] = min(100, round(load / os.cpu_count() * 100))
    except OSError:
        pass
    try:
        info = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
        total = int(info["MemTotal"].split()[0])
        free = int(info["MemAvailable"].split()[0])
        out["memory"] = round((total - free) / total * 100)
    except (OSError, KeyError, ValueError):
        pass
    for bat in Path("/sys/class/power_supply").glob("BAT*"):
        try:
            out["battery"] = int((bat / "capacity").read_text())
            out["charging"] = (bat / "status").read_text().strip() == "Charging"
        except (OSError, ValueError):
            pass
    return out


class Server:
    """Shares files and the wall page with the TV while Cast runs."""

    def __init__(self, tv_ip, place=lambda: None):
        self.tv_ip = tv_ip
        self.place = place
        self.host = local_ip_towards(tv_ip)
        self.token = secrets.token_urlsafe(12)
        self.files = {}
        self.httpd = None

    def start(self):
        if self.httpd:
            return
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_HEAD(self):
                self._serve(head=True)

            def do_GET(self):
                self._serve(head=False)

            def _serve(self, head):
                parts = self.path.split("?")[0].strip("/").split("/")
                if len(parts) < 2 or parts[0] != server.token:
                    self.send_error(404)
                    return
                if parts[1] == "wall":
                    self._send(200, "text/html; charset=utf-8", server.wall_page().encode(), head)
                elif parts[1] == "vitals":
                    self._send(200, "application/json", json.dumps(vitals(server.place())).encode(), head)
                elif parts[1] == "f" and len(parts) >= 3 and parts[2] in server.files:
                    self._file(server.files[parts[2]], head)
                else:
                    self.send_error(404)

            def _send(self, code, kind, body, head):
                self.send_response(code)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                if not head:
                    self.wfile.write(body)

            def _file(self, path, head):
                size = path.stat().st_size
                span = parse_range(self.headers.get("Range"), size)
                start, end = span or (0, size - 1)
                self.send_response(206 if span else 200)
                self.send_header("Content-Type", mimetypes.guess_type(path.name)[0]
                                 or "application/octet-stream")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(end - start + 1))
                if span:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                # DLNA renderers look for these before they agree to stream.
                self.send_header("transferMode.dlna.org", "Streaming")
                self.send_header("contentFeatures.dlna.org",
                                 "DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000")
                self.end_headers()
                if head:
                    return
                with path.open("rb") as handle:
                    handle.seek(start)
                    try:
                        remaining = end - start + 1
                        while remaining > 0:
                            chunk = handle.read(min(1 << 16, remaining))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        pass

        self.httpd = ThreadingHTTPServer((self.host, 0), Handler)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None

    @property
    def base(self):
        return f"http://{self.host}:{self.httpd.server_address[1]}/{self.token}"

    def share(self, path):
        path = Path(path).resolve()
        ident = secrets.token_urlsafe(8)
        self.files[ident] = path
        return f"{self.base}/f/{ident}/{quote(path.name)}"

    def wall_url(self):
        return f"{self.base}/wall"

    def wall_page(self):
        page = (HERE / "wall.html").read_text()
        return page.replace("@VITALS@", f"{self.base}/vitals").replace(
            "@HOST@", html.escape(socket.gethostname()))


# --- DLNA ------------------------------------------------------------------

def _soap(url, action, body):
    envelope = ('<?xml version="1.0" encoding="utf-8"?>'
                '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
                's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
                f'<u:{action} xmlns:u="{AVT}"><InstanceID>0</InstanceID>{body}</u:{action}>'
                '</s:Body></s:Envelope>').encode()
    request = urllib.request.Request(url, envelope, {
        "Content-Type": 'text/xml; charset="utf-8"', "SOAPAction": f'"{AVT}#{action}"'})
    with urllib.request.urlopen(request, timeout=6) as reply:
        return reply.read().decode("utf-8", "replace")


def renderer_control(tv_ip, port=1527):
    """The AVTransport control URL of the TV's DLNA renderer."""
    base = f"http://{tv_ip}:{port}"
    xml = urllib.request.urlopen(base + "/", timeout=4).read().decode("utf-8", "replace")
    for block in re.findall(r"<service>(.*?)</service>", xml, re.S):
        if AVT in block:
            control = re.search(r"<controlURL>([^<]+)</controlURL>", block).group(1)
            return control if control.startswith("http") else base + control
    raise OSError("The TV has no DLNA renderer")


def didl(title, url, mime):
    kind = {"video": "videoItem", "audio": "audioItem.musicTrack", "image": "imageItem.photo"}.get(
        mime.split("/")[0], "videoItem")
    return ('<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
            f'<item id="0" parentID="-1" restricted="1"><dc:title>{html.escape(title)}</dc:title>'
            f'<upnp:class>object.item.{kind}</upnp:class>'
            f'<res protocolInfo="http-get:*:{mime}:*">{html.escape(url)}</res></item></DIDL-Lite>')


def play_file(server, path, tv_ip):
    """Hand a local file to the TV. Blocking; run it off the main loop."""
    path = Path(path)
    url = server.share(path)
    mime = mimetypes.guess_type(path.name)[0] or "video/mp4"
    control = renderer_control(tv_ip)
    _soap(control, "SetAVTransportURI",
          f"<CurrentURI>{html.escape(url)}</CurrentURI>"
          f"<CurrentURIMetaData>{html.escape(didl(path.stem, url, mime))}</CurrentURIMetaData>")
    _soap(control, "Play", "<Speed>1</Speed>")
    return url


def transport(tv_ip, action):
    """Pause, Play or Stop whatever the renderer is playing."""
    body = "<Speed>1</Speed>" if action == "Play" else ""
    _soap(renderer_control(tv_ip), action, body)


def playable(path):
    mime = mimetypes.guess_type(str(path))[0] or ""
    return mime.split("/")[0] in ("video", "audio", "image")

