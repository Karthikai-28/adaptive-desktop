"""The media side of a cast: capture, draw, encode, send.

  capture (whole screen, one window, or a region of the screen)
    -> scale to the TV mode (fit, fill, or fit inside a safe margin)
    -> cairooverlay: privacy masks, freeze, cursor, clock, badge, caption, curtain
    -> tee -> encoder -> MPEG-TS over RTP to the TV (+ Matroska copy when recording)
           -> small RGB frames for the window's live preview

Everything drawn on the TV picture is drawn in one cairo callback, so each
feature is a few lines in Overlay.draw and the encoder never changes.
"""

import math
import time
from pathlib import Path

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstVideo", "1.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
gi.require_foreign("cairo")
import cairo  # noqa: E402
from gi.repository import GLib, Gst, GstVideo, Pango, PangoCairo  # noqa: E402

import desk  # noqa: E402
import wfd  # noqa: E402

Gst.init(None)

RECORD_DIR = Path.home() / "Videos/Cast"
SAFE_MARGIN = 0.94
PREVIEW_W, PREVIEW_H = 384, 216
# Corner pills sit below GNOME's top bar so they never cover its clock.
PILL_TOP = 44

ACCENT = (0x0A / 255, 0x84 / 255, 0xFF / 255)
SURFACE = (0x1C / 255, 0x1C / 255, 0x1E / 255)


def element(name):
    return Gst.ElementFactory.find(name) is not None


def pick_encoder():
    """Hardware H.264 first (Intel VA-API), then x264, then OpenH264."""
    for name in ("vaapih264enc", "x264enc", "openh264enc"):
        if element(name):
            return name
    return None


def aac_encoder():
    for name in ("voaacenc", "fdkaacenc", "avenc_aac"):
        if element(name):
            return name
    return None


def missing_elements():
    """GStreamer elements this needs that are not installed, by package."""
    need = {
        "mpegtsmux": "gstreamer1.0-plugins-bad",
        "h264parse": "gstreamer1.0-plugins-bad",
        "rtpmp2tpay": "gstreamer1.0-plugins-good",
        "ximagesrc": "gstreamer1.0-plugins-good",
        "cairooverlay": "gstreamer1.0-plugins-good",
    }
    out = {pkg for name, pkg in need.items() if not element(name)}
    if not pick_encoder():
        out.add("gstreamer1.0-vaapi")
    return sorted(out)


# --- pure pieces (scripts/verify-cast.py checks these) ---------------------

def source_element(source):
    base = "ximagesrc use-damage=false show-pointer=true"
    kind = source.get("kind", "screen")
    if kind == "window":
        return f"{base} xid={source['xid']}"
    if kind == "region":
        x, y, w, h = source["x"], source["y"], source["w"], source["h"]
        return f"{base} startx={x} starty={y} endx={x + w - 1} endy={y + h - 1}"
    return base


def _safe_size(width, height):
    return int(width * SAFE_MARGIN) // 2 * 2, int(height * SAFE_MARGIN) // 2 * 2


def fit_chain(fit, width, height):
    """Elements that turn any source size into exactly width x height."""
    if fit == "fill":
        return f"aspectratiocrop aspect-ratio={width}/{height} ! videoscale ! "
    if fit == "safe":
        iw, ih = _safe_size(width, height)
        left, top = (width - iw) // 2, (height - ih) // 2
        return (f"videoscale add-borders=true ! "
                f"video/x-raw,width={iw},height={ih},pixel-aspect-ratio=1/1 ! "
                f"videobox fill=black left=-{left} right=-{width - iw - left} "
                f"top=-{top} bottom=-{height - ih - top} ! ")
    return "videoscale add-borders=true ! "


def content_rect(src_w, src_h, frame_w, frame_h, fit):
    """(scale, ox, oy): a source pixel (x, y) lands at (ox + x*scale, oy + y*scale)."""
    if src_w <= 0 or src_h <= 0:
        return 1.0, 0.0, 0.0
    if fit == "fill":
        scale = max(frame_w / src_w, frame_h / src_h)
    elif fit == "safe":
        iw, ih = _safe_size(frame_w, frame_h)
        scale = min(iw / src_w, ih / src_h)
    else:
        scale = min(frame_w / src_w, frame_h / src_h)
    return scale, (frame_w - src_w * scale) / 2, (frame_h - src_h * scale) / 2


def encoder_chain(encoder, video, quality):
    preset = wfd.QUALITY[quality]
    gop = video["fps"]
    if encoder == "vaapih264enc":
        # Constant QP: on this Gen9 iGPU the iHD driver refuses CBR/VBR
        # (bitrate control needs HuC firmware the kernel does not load), so
        # quality is fixed instead. Desktop content stays far below the
        # 50 Mbps a WFD sink takes.
        return (f"vaapih264enc rate-control=cqp init-qp={preset['qp']} "
                f"keyframe-period={gop} max-bframes=0")
    if encoder == "x264enc":
        return (f"x264enc tune=zerolatency speed-preset=ultrafast bitrate={preset['kbps']}"
                f" key-int-max={gop} bframes=0 sliced-threads=true")
    return f"openh264enc bitrate={preset['kbps'] * 1000} gop-size={gop} complexity=low"


def pipeline_description(video, audio, host, port, encoder, source=None, fit="fit",
                         quality="sharp", audio_device=None, record_path=None, preview=False):
    """gst-launch text for the stream.

    PIDs 0x1011 (video) and 0x1100 (audio) are the ones WFD sinks expect;
    mpegtsmux takes the PID from the requested pad name.
    """
    source = source or {"kind": "screen"}
    width, height, fps = video["width"], video["height"], video["fps"]
    # VA-API takes only NV12 here; the software encoders want I420.
    raw_format = "NV12" if encoder == "vaapih264enc" else "I420"
    depth = 1 if quality == "game" else 2
    parts = [
        f"mpegtsmux name=mux alignment=7 ! rtpmp2tpay pt=33 ! "
        f"udpsink name=out host={host} port={port} sync=false async=false",
        f"{source_element(source)} ! video/x-raw,framerate={fps}/1 ! "
        f"queue name=capq leaky=downstream max-size-buffers={depth} max-size-time=0 "
        "max-size-bytes=0 ! videoconvert ! "
        f"{fit_chain(fit, width, height)}"
        f"video/x-raw,format=BGRx,width={width},height={height},pixel-aspect-ratio=1/1 ! "
        "cairooverlay name=draw ! tee name=vt",
        f"vt. ! queue max-size-buffers={depth} ! videoconvert ! video/x-raw,format={raw_format} ! "
        f"{encoder_chain(encoder, video, quality)} name=venc ! "
        "video/x-h264,profile=constrained-baseline ! "
        "h264parse config-interval=-1 ! video/x-h264,stream-format=byte-stream,alignment=au ! "
        "tee name=ht ht. ! queue ! mux.sink_4113",
    ]
    if preview:
        parts.append(
            "vt. ! queue leaky=downstream max-size-buffers=1 ! videorate drop-only=true ! "
            "video/x-raw,framerate=4/1 ! videoscale ! videoconvert ! "
            # RGB, not RGBA: cairo leaves the BGRx padding byte at 0, which
            # would turn into a fully transparent preview.
            f"video/x-raw,format=RGB,width={PREVIEW_W},height={PREVIEW_H} ! "
            "appsink name=preview drop=true max-buffers=1 emit-signals=true sync=false")
    if audio == "AAC":
        device = f" device={audio_device}" if audio_device else ""
        parts.append(
            f"pulsesrc{device} ! audioconvert ! audioresample ! "
            "audio/x-raw,rate=48000,channels=2 ! "
            f"{aac_encoder()} bitrate=128000 ! aacparse ! tee name=at at. ! queue ! mux.sink_4352")
    if record_path:
        parts.append(f"matroskamux name=rec ! filesink location=\"{record_path}\"")
        parts.append("ht. ! queue ! h264parse ! rec.")
        if audio == "AAC":
            parts.append("at. ! queue ! aacparse ! rec.")
    return "  ".join(parts)


def record_path():
    RECORD_DIR.mkdir(parents=True, exist_ok=True)
    return str(RECORD_DIR / time.strftime("Cast %Y-%m-%d %H.%M.%S.mkv"))


# --- what is drawn on the TV picture ---------------------------------------

class Overlay:
    """State read by the streaming thread on every frame; set from the main loop.

    Plain attribute writes, so no locking: a frame sees either the old value
    or the new one.
    """

    def __init__(self, source, fit, prefs):
        self.source = source
        self.fit = fit
        self.cursor = prefs.get("cursor", "ring")
        self.clock = prefs.get("clock", False)
        self.badge = prefs.get("badge", "")
        self.caption = prefs.get("caption", "")
        self.masks = []            # screen rectangles to black out
        self.freeze = False
        self.curtain = None        # None, or text for the "be right back" screen
        self.src_size = (0, 0)
        self.frame_size = (0, 0)
        self.pointer = desk.Pointer()
        self._snapshot = None
        self._pressed_at = 0.0

    def _origin(self):
        kind = self.source.get("kind", "screen")
        if kind == "region":
            return self.source["x"], self.source["y"]
        if kind == "window":
            return self.pointer.window_origin(self.source["xid"])
        return 0, 0

    def on_caps(self, _ov, caps):
        info = GstVideo.VideoInfo.new_from_caps(caps)
        self.frame_size = (info.width, info.height)

    def draw(self, _ov, cr, _ts, _dur):
        fw, fh = self.frame_size
        if not fw:
            return
        sw, sh = self.src_size
        scale, ox, oy = content_rect(sw or fw, sh or fh, fw, fh, self.fit)
        gx, gy = self._origin()

        def to_frame(x, y):
            return ox + (x - gx) * scale, oy + (y - gy) * scale

        for (x, y, w, h) in list(self.masks):
            fx, fy = to_frame(x, y)
            cr.new_path()
            _rounded(cr, fx, fy, w * scale, h * scale, 10 * scale)
            cr.set_source_rgb(*SURFACE)
            cr.fill_preserve()
            cr.set_line_width(2)
            cr.set_source_rgba(1, 1, 1, 0.18)
            cr.stroke()
            _text(cr, "Hidden while casting", fx + w * scale / 2, fy + h * scale / 2,
                  size=max(14, 22 * scale), align="center", alpha=0.6)

        if self.freeze:
            if self._snapshot is None:
                snap = cairo.ImageSurface(cairo.FORMAT_RGB24, fw, fh)
                ctx = cairo.Context(snap)
                ctx.set_source_surface(cr.get_target())
                ctx.paint()
                self._snapshot = snap
            cr.set_source_surface(self._snapshot)
            cr.paint()
        else:
            self._snapshot = None
            self._draw_cursor(cr, to_frame, fw, fh, scale)

        if self.clock:
            self._pill(cr, time.strftime("%H:%M"), fw - 24, PILL_TOP, anchor="right")
        if self.badge:
            self._pill(cr, self.badge, 24, PILL_TOP, anchor="left")
        if self.freeze and self.curtain is None:
            self._pill(cr, "Paused", fw / 2, PILL_TOP, anchor="center")
        if self.caption:
            self._caption(cr, self.caption, fw, fh)
        if self.curtain is not None:
            self._curtain(cr, fw, fh)

    def _draw_cursor(self, cr, to_frame, fw, fh, scale):
        if self.cursor == "off":
            return
        where = self.pointer.position()
        if not where:
            return
        x, y = to_frame(where[0], where[1])
        if not (0 <= x < fw and 0 <= y < fh):
            return
        # Text leaves a current point behind; an arc from there draws a line.
        cr.new_path()
        if where[2]:
            self._pressed_at = time.monotonic()
        pulse = max(0.0, 1 - (time.monotonic() - self._pressed_at) / 0.4)
        if self.cursor == "spotlight":
            cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
            cr.rectangle(0, 0, fw, fh)
            cr.arc(x, y, 170, 0, 2 * math.pi)
            cr.set_source_rgba(0, 0, 0, 0.55)
            cr.fill()
            cr.set_fill_rule(cairo.FILL_RULE_WINDING)
            return
        radius = 26 + 14 * pulse
        cr.arc(x, y, radius, 0, 2 * math.pi)
        cr.set_source_rgba(*ACCENT, 0.22 + 0.25 * pulse)
        cr.fill_preserve()
        cr.set_line_width(3)
        cr.set_source_rgba(*ACCENT, 0.9)
        cr.stroke()

    def _pill(self, cr, text, x, y, anchor):
        layout = _layout(cr, text, 20, bold=True)
        tw, th = (v / Pango.SCALE for v in layout.get_size())
        w, h = tw + 28, th + 14
        left = {"left": x, "right": x - w, "center": x - w / 2}[anchor]
        cr.new_path()
        _rounded(cr, left, y, w, h, h / 2)
        cr.set_source_rgba(*SURFACE, 0.82)
        cr.fill_preserve()
        # An outline so the pill reads on dark windows too.
        cr.set_line_width(1.5)
        cr.set_source_rgba(*ACCENT, 0.75)
        cr.stroke()
        cr.move_to(left + 14, y + 7)
        cr.set_source_rgb(1, 1, 1)
        PangoCairo.show_layout(cr, layout)

    def _caption(self, cr, text, fw, fh):
        layout = _layout(cr, text, 30, width=fw - 160)
        layout.set_alignment(Pango.Alignment.CENTER)
        tw, th = (v / Pango.SCALE for v in layout.get_size())
        h = th + 32
        cr.rectangle(0, fh - h - 40, fw, h)
        cr.set_source_rgba(0, 0, 0, 0.62)
        cr.fill()
        cr.move_to(80, fh - h - 40 + 16)
        cr.set_source_rgb(1, 1, 1)
        PangoCairo.show_layout(cr, layout)

    def _curtain(self, cr, fw, fh):
        cr.rectangle(0, 0, fw, fh)
        cr.set_source_rgb(0x14 / 255, 0x14 / 255, 0x16 / 255)
        cr.fill()
        glow = cairo.RadialGradient(fw / 2, fh / 2, 0, fw / 2, fh / 2, fw / 1.6)
        glow.add_color_stop_rgba(0, *ACCENT, 0.20)
        glow.add_color_stop_rgba(1, *ACCENT, 0.0)
        cr.set_source(glow)
        cr.paint()
        _text(cr, time.strftime("%H:%M"), fw / 2, fh / 2 - 90, size=120, align="center", bold=True)
        _text(cr, self.curtain or "Back in a moment", fw / 2, fh / 2 + 50, size=40,
              align="center", alpha=0.85)


def _rounded(cr, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def _layout(cr, text, size, bold=False, width=None):
    layout = PangoCairo.create_layout(cr)
    font = Pango.FontDescription.from_string(f"Ubuntu {'Bold ' if bold else ''}{int(size)}px")
    font.set_absolute_size(size * Pango.SCALE)
    layout.set_font_description(font)
    if width:
        layout.set_width(int(width * Pango.SCALE))
        layout.set_wrap(Pango.WrapMode.WORD_CHAR)
    layout.set_text(text, -1)
    return layout


def _text(cr, text, x, y, size, align="left", bold=False, alpha=1.0):
    layout = _layout(cr, text, size, bold)
    tw, th = (v / Pango.SCALE for v in layout.get_size())
    left = x - tw / 2 if align == "center" else x
    cr.move_to(left, y - th / 2)
    cr.set_source_rgba(1, 1, 1, alpha)
    PangoCairo.show_layout(cr, layout)


# --- the running pipeline --------------------------------------------------

class Stream:
    """One running pipeline. on_error(text) is called on the main loop."""

    def __init__(self, video, audio, host, port, prefs, source, audio_device, on_error,
                 log=print, preview=False):
        self.video = video
        self.audio = audio
        self.prefs = prefs
        self.source = source
        self.on_error = on_error
        self.log = log
        self.encoder = pick_encoder()
        self.record_path = record_path() if prefs.get("record") else None
        self.overlay = Overlay(source, prefs.get("fit", "fit"), prefs)
        self.description = pipeline_description(
            video, audio, host, port, self.encoder, source, prefs.get("fit", "fit"),
            prefs.get("quality", "sharp"), audio_device, self.record_path, preview)
        self.pipeline = None
        self.started = 0.0
        self._bytes = self._frames = self._dropped = 0
        self._last = (0.0, 0, 0)
        self._rate = {"kbps": 0, "fps": 0}
        self._preview = None
        self._poll = 0

    def start(self):
        self.log(f"cast: {self.description}")
        self.pipeline = Gst.parse_launch(self.description)
        draw = self.pipeline.get_by_name("draw")
        draw.connect("draw", self.overlay.draw)
        draw.connect("caps-changed", self.overlay.on_caps)
        self.pipeline.get_by_name("capq").connect("overrun", self._overrun)
        self.pipeline.get_by_name("out").get_static_pad("sink").add_probe(
            Gst.PadProbeType.BUFFER, self._count_bytes)
        self.pipeline.get_by_name("venc").get_static_pad("src").add_probe(
            Gst.PadProbeType.BUFFER, self._count_frame)
        preview = self.pipeline.get_by_name("preview")
        if preview:
            preview.connect("new-sample", self._on_preview)
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", self._on_error)
        self._update_source()
        self.pipeline.set_state(Gst.State.PLAYING)
        self.started = time.monotonic()
        self._last = (self.started, 0, 0)
        self._poll = GLib.timeout_add_seconds(1, self._tick)

    def stop(self):
        if self._poll:
            GLib.source_remove(self._poll)
            self._poll = 0
        if not self.pipeline:
            return
        if self.record_path:
            # Matroska is readable without this, but EOS writes the index so
            # the recording can be scrubbed.
            self.pipeline.send_event(Gst.Event.new_eos())
            self.pipeline.get_bus().timed_pop_filtered(
                3 * Gst.SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
        self.pipeline.set_state(Gst.State.NULL)
        self.pipeline = None
        self.overlay.pointer.close()

    def pause(self, paused):
        if self.pipeline:
            self.pipeline.set_state(Gst.State.PAUSED if paused else Gst.State.PLAYING)

    def force_keyframe(self):
        venc = self.pipeline.get_by_name("venc") if self.pipeline else None
        if venc:
            venc.get_static_pad("src").send_event(
                GstVideo.video_event_new_upstream_force_key_unit(Gst.CLOCK_TIME_NONE, True, 0))

    # --- once a second: masks, source size, rates -----------------------

    def _update_source(self):
        kind = self.source.get("kind", "screen")
        if kind == "region":
            self.overlay.src_size = (self.source["w"], self.source["h"])
        elif kind == "window":
            for win in desk.windows():
                if win["xid"] == self.source["xid"]:
                    self.overlay.src_size = (win["w"], win["h"])
        else:
            self.overlay.src_size = desk.screen_size()
        if kind != "window" and self.prefs.get("hide_windows"):
            self.overlay.masks = desk.sensitive_rects(self.prefs.get("hidden_classes", []))
        else:
            self.overlay.masks = []

    def _tick(self):
        self._update_source()
        now = time.monotonic()
        then, bytes_then, frames_then = self._last
        span = max(0.001, now - then)
        self._rate = {"kbps": int((self._bytes - bytes_then) * 8 / span / 1000),
                      "fps": round((self._frames - frames_then) / span)}
        self._last = (now, self._bytes, self._frames)
        return GLib.SOURCE_CONTINUE

    def stats(self):
        return {**self._rate, "dropped": self._dropped,
                "seconds": int(time.monotonic() - self.started) if self.started else 0,
                "encoder": self.encoder, "recording": self.record_path,
                "width": self.video["width"], "height": self.video["height"],
                "mode_fps": self.video["fps"]}

    def preview(self):
        """(RGB bytes, width, height, stride) of the latest small frame, or None."""
        return self._preview

    # --- streaming-thread callbacks --------------------------------------

    def _overrun(self, _queue):
        self._dropped += 1

    def _count_bytes(self, _pad, info):
        buffer = info.get_buffer()
        if buffer:
            self._bytes += buffer.get_size()
        return Gst.PadProbeReturn.OK

    def _count_frame(self, _pad, _info):
        self._frames += 1
        return Gst.PadProbeReturn.OK

    def _on_preview(self, sink):
        sample = sink.emit("pull-sample")
        if sample:
            buffer = sample.get_buffer()
            ok, info = buffer.map(Gst.MapFlags.READ)
            if ok:
                self._preview = (bytes(info.data), PREVIEW_W, PREVIEW_H, PREVIEW_W * 3)
                buffer.unmap(info)
        return Gst.FlowReturn.OK

    def _on_error(self, _bus, message):
        error, _debug = message.parse_error()
        self.on_error(f"Stream stopped: {error.message}")
