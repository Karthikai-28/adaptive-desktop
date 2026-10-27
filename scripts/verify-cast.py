#!/usr/bin/env python3
"""Cast (apps/adaptive-cast): the Miracast logic that needs no TV.

Checks the WFD element we advertise and how a sink's is read, RTSP framing
across split reads, the format choice from real sink replies, and that the
stream description is one GStreamer can parse when the elements exist.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "apps/adaptive-cast"))

import wfd  # noqa: E402

failures = []


def check(name, ok):
    if not ok:
        failures.append(name)
        print(f"FAIL {name}")


# The element our LG TV advertises (seen over NetworkManager).
lg = wfd.parse_ies(bytes([0, 0, 6, 1, 19, 28, 68, 0, 50]))
check("LG IE is dual role", lg.get("device_type") == "dual role")
check("LG IE session available", lg.get("session_available") is True)
check("LG IE port 7236", lg.get("rtsp_port") == 7236)
check("LG IE content protection", lg.get("content_protection") is True)
check("LG IE is a sink", wfd.is_sink(lg))

ours = wfd.parse_ies(wfd.source_ies())
check("our IE is a source", ours.get("device_type") == "source")
check("our IE is available", ours.get("session_available") is True)
check("our IE names the control port", ours.get("rtsp_port") == wfd.CONTROL_PORT)
check("our IE is not a sink", not wfd.is_sink(ours))
check("empty IE", wfd.parse_ies(b"") == {} and wfd.parse_ies(None) == {})

# RTSP framing: a reply with a body, split mid-header and mid-body.
reply = wfd.response(3, body="wfd_video_formats: none\r\nwfd_client_rtp_ports: "
                             "RTP/AVP/UDP;unicast 19000 0 mode=play\r\n")
msg, rest = wfd.take_message(reply[:20])
check("partial header waits", msg is None and rest == reply[:20])
msg, rest = wfd.take_message(reply[:-5])
check("partial body waits", msg is None)
msg, rest = wfd.take_message(reply + wfd.request("SETUP", "rtsp://x/wfd1.0/streamid=0", 4))
check("reply parsed", msg is not None and msg.is_response and msg.status == 200 and msg.cseq == 3)
check("rtp port read", wfd.client_rtp_port(wfd.parameters(msg.body)["wfd_client_rtp_ports"]) == 19000)
nxt, rest = wfd.take_message(rest)
check("second message follows", nxt is not None and nxt.method == "SETUP" and nxt.cseq == 4 and rest == b"")

# Format choice from sink replies.
lg_formats = "00 00 03 10 0001ffff 1fffffff 00000fff 00 0000 0000 10 none none"
video = wfd.choose_video(lg_formats)
check("1080p30 chosen", (video["width"], video["height"], video["fps"]) == (1920, 1080, 30))
check("level 4 for 1080p30", video["level"] == wfd.LEVEL_4)
check("M4 names one mode", wfd.video_formats_value(video).split()[4] == f"{1 << 7:08x}")

low = wfd.choose_video("00 00 01 01 000000ff 00000000 00000000 00 0000 0000 00 none none")
check("level 3.1 caps at 720p30", (low["width"], low["height"], low["fps"]) == (1280, 720, 30))
check("High-only falls back to 480p", wfd.choose_video(
    "00 00 02 10 0001ffff 00000000 00000000 00 0000 0000 00 none none")["height"] == 480)
check("two codec entries", wfd.choose_video(
    "00 00 02 10 0001ffff 0 0 00 0000 0000 00 none none, "
    "01 08 000000a0 0 0 00 0000 0000 00 none none")["height"] == 1080)
check("no video formats", wfd.choose_video("none") is None)

check("AAC chosen", wfd.choose_audio("LPCM 00000003 00, AAC 0000000f 00") == "AAC")
check("LPCM only means no sound", wfd.choose_audio("LPCM 00000003 00") is None)
check("no encoder means no sound", wfd.choose_audio("AAC 0000000f 00", have_aac=False) is None)

# The stream description parses when every element is installed.
try:
    import session
    from gi.repository import Gst
    if not session.missing_elements():
        for encoder in ("vaapih264enc", "x264enc", "openh264enc"):
            if not session.element(encoder):
                continue
            text = session.pipeline_description(video, "AAC" if session.have_aac() else None,
                                                "127.0.0.1", 19000, encoder)
            try:
                Gst.parse_launch(text)
            except Exception as error:  # noqa: BLE001
                check(f"pipeline parses with {encoder}: {error}", False)
    else:
        print(f"skip pipeline: missing {', '.join(session.missing_elements())}")
except ImportError as error:
    print(f"skip pipeline: {error}")

if failures:
    sys.exit(1)
print("cast checks passed")
