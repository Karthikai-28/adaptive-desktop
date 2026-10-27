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

check("quality presets", all(wfd.choose_video(lg_formats, order=wfd.QUALITY[q]["order"])
                             for q in wfd.QUALITY))
check("smooth is 1080p60", wfd.choose_video(lg_formats, order=wfd.QUALITY["smooth"]["order"])
      ["fps"] == 60)
check("light is 720p", wfd.choose_video(lg_formats, order=wfd.QUALITY["light"]["order"])
      ["height"] == 720)

try:
    import stream
    from gi.repository import Gst
except (ImportError, ValueError) as error:
    stream = None
    print(f"skip stream: {error}")

if stream:
    # Where a source pixel lands on the TV frame.
    check("fit letterboxes 16:10", stream.content_rect(1920, 1200, 1920, 1080, "fit")
          == (0.9, 96.0, 0.0))
    check("fill crops 16:10", stream.content_rect(1920, 1200, 1920, 1080, "fill")
          == (1.0, 0.0, -60.0))
    scale, ox, oy = stream.content_rect(1920, 1080, 1920, 1080, "safe")
    check("safe keeps a margin", scale < 0.95 and ox > 50 and oy > 30)
    check("region source", "startx=10 starty=20 endx=109 endy=219" in stream.source_element(
        {"kind": "region", "x": 10, "y": 20, "w": 100, "h": 200}))
    check("window source", "xid=4242" in stream.source_element({"kind": "window", "xid": 4242}))

    def run(text, overlay=None, seconds=10):
        """Run with test sources: the encoder only refuses a setting once caps
        reach it, which parsing alone never shows."""
        text = text.replace("ximagesrc use-damage=false show-pointer=true",
                            "videotestsrc is-live=true num-buffers=15")
        text = text.replace("pulsesrc", "audiotestsrc is-live=true num-buffers=15")
        try:
            pipe = Gst.parse_launch(text)
        except Exception as error:  # noqa: BLE001
            return str(error)
        if overlay:
            draw = pipe.get_by_name("draw")
            draw.connect("draw", overlay.draw)
            draw.connect("caps-changed", overlay.on_caps)
        preview = pipe.get_by_name("preview")
        if preview:
            # appsink reports end-of-stream only once its last frame is taken,
            # as the window does.
            preview.connect("new-sample", lambda sink: sink.emit("pull-sample") and
                            Gst.FlowReturn.OK)
        pipe.set_state(Gst.State.PLAYING)
        message = pipe.get_bus().timed_pop_filtered(
            seconds * Gst.SECOND, Gst.MessageType.ERROR | Gst.MessageType.EOS)
        pipe.set_state(Gst.State.NULL)
        if message is None:
            return "timed out"
        return message.parse_error()[0].message if message.type == Gst.MessageType.ERROR else None

    if stream.missing_elements():
        print(f"skip pipeline: missing {', '.join(stream.missing_elements())}")
    else:
        aac = "AAC" if stream.aac_encoder() else None
        cases = []
        for encoder in ("vaapih264enc", "x264enc", "openh264enc"):
            if stream.element(encoder):
                cases.append((encoder, "fit", "sharp", False, False))
        if stream.element("vaapih264enc"):
            cases += [("vaapih264enc", "fill", "smooth", False, True),
                      ("vaapih264enc", "safe", "game", True, False)]
        import tempfile
        tmp = tempfile.mkdtemp(prefix="verify-cast-")
        for encoder, fit, quality, record, preview in cases:
            mode = wfd.choose_video(lg_formats, order=wfd.QUALITY[quality]["order"])
            path = f"{tmp}/rec.mkv" if record else None
            text = stream.pipeline_description(mode, aac, "127.0.0.1", 19000, encoder, None, fit,
                                               quality, None, path, preview)
            # Every overlay on at once, frozen behind a curtain; it must not
            # slow the stream or raise in the streaming thread.
            overlay = stream.Overlay({"kind": "screen"}, fit,
                                     {"cursor": "spotlight", "clock": True, "badge": "Badge",
                                      "caption": "A caption long enough to wrap " * 4})
            overlay.masks = [(100, 100, 400, 300)]
            overlay.freeze = True
            overlay.curtain = "Back soon"
            reason = run(text, overlay)
            check(f"pipeline runs: {encoder} {fit} {quality} record={record} "
                  f"preview={preview}: {reason}", reason is None)
            if record:
                check("recording written", Path(path).exists() and Path(path).stat().st_size > 0)

        # The cursor is read from X on every frame, from GStreamer's thread.
        # It must reuse one connection: a new one per frame used up X's
        # client limit within seconds and froze the desktop.
        import os
        if os.environ.get("DISPLAY"):
            overlay = stream.Overlay({"kind": "screen"}, "fit", {"cursor": "ring"})
            reason = run("videotestsrc is-live=true num-buffers=40 ! "
                         "video/x-raw,format=BGRx,width=640,height=360,framerate=30/1 ! "
                         "cairooverlay name=draw ! fakesink", overlay)
            check(f"cursor overlay runs: {reason}", reason is None)
            check(f"one X connection for the cursor ({len(overlay.pointer._displays)} opened)",
                  1 <= len(overlay.pointer._displays) <= 2)
            overlay.pointer.close()

if failures:
    sys.exit(1)
print("cast checks passed")
