"""Wi-Fi Display (Miracast) protocol pieces with no I/O.

Everything here is pure so scripts/verify-cast.py can check it without a TV:
the WFD information element we advertise, reading a sink's element, the RTSP
framing used on the control channel, and choosing a video and audio format
from what the sink says it can play.

The source is the RTSP server on port 7236 here. The sink connects, then
the source drives the exchange (M1..M7 in the WFD spec) and sends MPEG-TS
over RTP to the UDP port the sink named.
"""

import re

CONTROL_PORT = 7236
MAX_THROUGHPUT_MBPS = 50

DEVICE_TYPES = {0: "source", 1: "primary sink", 2: "secondary sink", 3: "dual role"}

# Bit position in the CEA mask of wfd_video_formats -> (width, height, fps).
# Only progressive modes; a desktop has no use for interlaced output.
CEA_MODES = {
    0: (640, 480, 60),
    1: (720, 480, 60),
    3: (720, 576, 50),
    5: (1280, 720, 30),
    6: (1280, 720, 60),
    7: (1920, 1080, 30),
    8: (1920, 1080, 60),
    10: (1280, 720, 25),
    11: (1280, 720, 50),
    12: (1920, 1080, 25),
    13: (1920, 1080, 50),
    15: (1280, 720, 24),
    16: (1920, 1080, 24),
}

# Preference order for a screen mirror: 1080p30 is sharp and light enough for
# a software or VA-API encoder; 60 fps doubles the bitrate for little gain on
# text, so it comes after the 30 fps modes.
PREFERRED_CEA = (7, 5, 8, 6, 12, 10, 0)

# Quality presets: the CEA modes each one tries, best first, and the
# constant QP (VA-API) or bitrate (software encoders) it encodes at.
QUALITY = {
    "sharp": {"label": "Sharp", "detail": "1080p 30 fps, crisp text", "order": (7, 5, 0),
              "qp": 23, "kbps": 9000},
    "smooth": {"label": "Smooth", "detail": "1080p 60 fps, for video and scrolling",
               "order": (8, 6, 7, 5, 0), "qp": 26, "kbps": 12000},
    "light": {"label": "Light", "detail": "720p 30 fps, for a weak signal", "order": (5, 10, 0),
              "qp": 30, "kbps": 4000},
    "game": {"label": "Game", "detail": "720p 60 fps, shortest delay", "order": (6, 5, 0),
             "qp": 28, "kbps": 6000},
}

PROFILE_CBP, PROFILE_CHP = 0x01, 0x02
# Level bits and the CEA modes each level can carry for Constrained Baseline.
LEVEL_31, LEVEL_32, LEVEL_4, LEVEL_41, LEVEL_42 = 0x01, 0x02, 0x04, 0x08, 0x10
LEVEL_NAMES = {LEVEL_31: "3.1", LEVEL_32: "3.2", LEVEL_4: "4", LEVEL_41: "4.1", LEVEL_42: "4.2"}


def source_ies(session_available=True):
    """WFD subelements for wifi-p2p.wfd-ies: one Device Information element.

    Device type 0 is a source; bit 4 says a session can start now. The port
    is where the sink will open the RTSP control connection.
    """
    info = 0x0000 | (0x0010 if session_available else 0)
    body = info.to_bytes(2, "big") + CONTROL_PORT.to_bytes(2, "big") + MAX_THROUGHPUT_MBPS.to_bytes(2, "big")
    return bytes([0x00]) + len(body).to_bytes(2, "big") + body


def parse_ies(data):
    """Read a peer's WFD subelements. Returns {} when there are none."""
    data = bytes(data or b"")
    out = {}
    pos = 0
    while pos + 3 <= len(data):
        sub_id = data[pos]
        length = int.from_bytes(data[pos + 1:pos + 3], "big")
        body = data[pos + 3:pos + 3 + length]
        pos += 3 + length
        if sub_id == 0x00 and len(body) >= 6:
            info = int.from_bytes(body[0:2], "big")
            out.update({
                "device_type": DEVICE_TYPES[info & 0x3],
                "session_available": (info >> 4) & 0x3 == 1,
                "content_protection": bool(info & 0x100),
                "rtsp_port": int.from_bytes(body[2:4], "big"),
                "max_mbps": int.from_bytes(body[4:6], "big"),
            })
    return out


def is_sink(ies):
    return ies.get("device_type") in ("primary sink", "secondary sink", "dual role")


# --- RTSP framing ----------------------------------------------------------

class Message:
    """One RTSP request or response, as it arrives on the control socket."""

    def __init__(self, first_line, headers, body=""):
        self.first_line = first_line
        self.headers = headers
        self.body = body

    @property
    def is_response(self):
        return self.first_line.startswith("RTSP/")

    @property
    def status(self):
        return int(self.first_line.split()[1]) if self.is_response else None

    @property
    def method(self):
        return None if self.is_response else self.first_line.split()[0]

    @property
    def cseq(self):
        return int(self.header("CSeq", "0"))

    def header(self, name, default=None):
        for key, value in self.headers.items():
            if key.lower() == name.lower():
                return value
        return default

    def __repr__(self):
        return f"<{self.first_line}>"


def take_message(buffer):
    """Split one complete message off the front of buffer (bytes).

    Returns (Message, rest) or (None, buffer) while the message is still
    arriving, so the caller can keep appending to the same buffer.
    """
    end = buffer.find(b"\r\n\r\n")
    if end < 0:
        return None, buffer
    head = buffer[:end].decode("utf-8", "replace").split("\r\n")
    headers = {}
    for line in head[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip()] = value.strip()
    length = 0
    for key, value in headers.items():
        if key.lower() == "content-length":
            length = int(value)
    start = end + 4
    if len(buffer) < start + length:
        return None, buffer
    body = buffer[start:start + length].decode("utf-8", "replace")
    return Message(head[0], headers, body), buffer[start + length:]


def build(first_line, cseq, headers=None, body=""):
    lines = [first_line, f"CSeq: {cseq}"]
    for key, value in (headers or {}).items():
        lines.append(f"{key}: {value}")
    if body:
        lines.append("Content-Type: text/parameters")
        lines.append(f"Content-Length: {len(body.encode())}")
    return ("\r\n".join(lines) + "\r\n\r\n" + body).encode()


def request(method, uri, cseq, headers=None, body=""):
    return build(f"{method} {uri} RTSP/1.0", cseq, headers, body)


def response(cseq, headers=None, body="", status=200, reason="OK"):
    return build(f"RTSP/1.0 {status} {reason}", cseq, headers, body)


def parameters(body):
    """'name: value' lines of a GET_PARAMETER reply -> dict."""
    out = {}
    for line in body.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            out[key.strip()] = value.strip()
    return out


# --- format choice ---------------------------------------------------------

def _max_level(levels):
    best = 0
    for bit in (LEVEL_31, LEVEL_32, LEVEL_4, LEVEL_41, LEVEL_42):
        if levels & bit:
            best = bit
    return best


def _level_for(width, height, fps):
    """Smallest H.264 level that carries this mode (macroblocks per second)."""
    mbps = (width // 16) * ((height + 15) // 16) * fps
    if mbps <= 108000:
        return LEVEL_31
    if mbps <= 216000:
        return LEVEL_32
    if mbps <= 245760:
        return LEVEL_4
    return LEVEL_42


def choose_video(sink_formats, max_height=1080, order=PREFERRED_CEA):
    """Pick a mode from the sink's wfd_video_formats value.

    The value is "native preferred-mode" followed by one or more
    comma-separated H.264 codec entries: "profile level CEA VESA HH latency
    min-slice slice-enc frame-rate-ctl max-hres max-vres". Only Constrained
    Baseline is used, which every sink must accept.
    """
    value = (sink_formats or "").strip()
    if not value or value == "none":
        return None
    parts = value.split()
    if len(parts) < 3:
        return None
    entries = " ".join(parts[2:]).split(",")
    best = None
    for entry in entries:
        fields = entry.split()
        if len(fields) < 5:
            continue
        profile, level = int(fields[0], 16), int(fields[1], 16)
        cea = int(fields[2], 16)
        if not profile & PROFILE_CBP:
            continue
        top = _max_level(level)
        for bit in order:
            if not cea & (1 << bit):
                continue
            width, height, fps = CEA_MODES[bit]
            need = _level_for(width, height, fps)
            if height > max_height or need > top:
                continue
            rank = order.index(bit)
            if best is None or rank < best["rank"]:
                best = {"rank": rank, "cea_bit": bit, "width": width, "height": height,
                        "fps": fps, "level": need}
            break
    if best is None:
        # Every sink must take 640x480p60 Constrained Baseline 3.1.
        best = {"rank": len(order), "cea_bit": 0, "width": 640, "height": 480,
                "fps": 60, "level": LEVEL_31}
    best.pop("rank")
    return best


def video_formats_value(video):
    """wfd_video_formats for SET_PARAMETER (M4): exactly the chosen mode."""
    cea = 1 << video["cea_bit"]
    return (f"00 00 {PROFILE_CBP:02x} {video['level']:02x} {cea:08x} 00000000 00000000"
            " 00 0000 0000 00 none none")


def choose_audio(sink_codecs, have_aac=True):
    """"AAC" when the sink takes AAC 48 kHz stereo, else None (video only).

    LPCM is mandatory for sinks, but WFD carries it in MPEG-TS with a private
    header mpegtsmux does not write, so it is not offered here.
    """
    value = (sink_codecs or "").strip()
    if not have_aac or not value or value == "none":
        return None
    for entry in value.split(","):
        fields = entry.split()
        # AAC mode bit 0 is 48 kHz, 2 channels.
        if len(fields) >= 2 and fields[0].upper() == "AAC" and int(fields[1], 16) & 0x1:
            return "AAC"
    return None


def audio_codecs_value(codec):
    return {"AAC": "AAC 00000001 00"}[codec]


def client_rtp_port(value):
    """First RTP port from wfd_client_rtp_ports ('RTP/AVP/UDP;unicast 19000 0 mode=play')."""
    match = re.search(r"unicast\s+(\d+)", value or "")
    return int(match.group(1)) if match else None
