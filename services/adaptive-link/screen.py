"""Adaptive Link - the laptop's screen as a stream of JPEG frames.

GStreamer captures the X screen, scales it and encodes each frame; the
newest frame waits in a one-slot buffer and an older one is dropped rather
than queued, so a slow connection gets a lower frame rate, never a growing
delay. A frame identical to the last one sent is skipped.

JPEG rather than video: every frame stands alone, so it decodes on any phone
with no codec negotiation and a lost connection resumes on the next frame.
The cost is bandwidth, which scale, quality and rate keep in hand.
"""

import hashlib
import re

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

Gst.init(None)

PRESETS = {
    # name: (longest side in pixels, JPEG quality, frames per second)
    "low": (960, 45, 8),
    "medium": (1280, 60, 12),
    "high": (1920, 75, 15),
    # Over a USB cable, where there is room for it.
    "cable": (1920, 80, 30),
}


def fit(width, height, longest):
    """(w, h) scaled so the longer side is at most `longest`, both even."""
    if width <= 0 or height <= 0:
        return 0, 0
    scale = min(1.0, longest / max(width, height))
    return max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2)


def source(region=None, display=None):
    """The part of the screen to capture: all of it, or one display
    (x, y, width, height)."""
    explicit = ""
    if display is not None:
        if not re.fullmatch(r":\d+", display):
            raise ValueError("invalid private display")
        explicit = f'display-name="{display}" '
    if not region:
        return "ximagesrc use-damage=false show-pointer=true " + explicit
    x, y, width, height = (int(value) for value in region)
    return (f"ximagesrc use-damage=false show-pointer=true startx={x} starty={y} "
            f"endx={x + width - 1} endy={y + height - 1} " + explicit)


def pipeline_description(width, height, preset, region=None, display=None):
    longest, quality, rate = PRESETS.get(preset, PRESETS["medium"])
    if region:
        width, height = region[2], region[3]
    out_w, out_h = fit(width, height, longest)
    return (
        source(region, display)
        + f"! video/x-raw,framerate={rate}/1 "
        "! videoscale method=bilinear "
        f"! video/x-raw,width={out_w},height={out_h} "
        "! videoconvert "
        f"! jpegenc quality={quality} "
        "! appsink name=sink max-buffers=1 drop=true sync=false emit-signals=false"
    )


class Capture:
    def __init__(self, screen, preset="medium", region=None, display=None, env=None):
        self.env = env
        self.pipe = None
        self.display = display
        self.screen = screen
        self.region = region
        self.preset = preset if preset in PRESETS else "medium"
        self._pipeline = None
        self._sink = None
        self._last = b""

    def start(self):
        if self.env is not None:
            self.pipe = PipedSource(pipeline_description(*self.screen, self.preset, self.region, self.display), self.env)
            self.pipe.start()
            return
        self._pipeline = Gst.parse_launch(pipeline_description(*self.screen, self.preset, self.region, self.display))
        self._sink = self._pipeline.get_by_name("sink")
        self._pipeline.set_state(Gst.State.PLAYING)

    def next_frame(self, timeout_s=1.0):
        """The next frame as JPEG bytes, or None if nothing new arrived.

        Blocking: call it from a worker thread.
        """
        if self.pipe is not None:
            return self.pipe.pull(timeout_s)
        # The action signal, so the GstApp typelib is not needed.
        sample = self._sink.emit("try-pull-sample", int(timeout_s * Gst.SECOND))
        if sample is None:
            return None
        buffer = sample.get_buffer()
        ok, info = buffer.map(Gst.MapFlags.READ)
        if not ok:
            return None
        try:
            data = bytes(info.data)
        finally:
            buffer.unmap(info)
        digest = hashlib.blake2b(data, digest_size=16).digest()
        if digest == self._last:
            return None
        self._last = digest
        return data

    def stop(self):
        if self.pipe is not None:
            self.pipe.stop()
            self.pipe = None
        if self._pipeline is not None:
            self._pipeline.set_state(Gst.State.NULL)
            self._pipeline = None
            self._sink = None


class MadeCapture:
    """The same frames as Capture, from a display made for a phone: taken
    from what the display itself was given to show (virtual_display.py), and
    only when it changed, rather than captured again from the screen."""

    def __init__(self, display, preset="medium"):
        self.display = display
        self.preset = preset if preset in PRESETS else "medium"
        self._seen = -1
        self._sent = 0.0

    def start(self):
        pass

    def next_frame(self, timeout_s=1.0):
        """The next frame as JPEG bytes, or None if nothing changed. Blocking."""
        import time

        from PIL import Image

        # No more often than the preset's rate, however often it changes.
        time.sleep(max(0.0, self._sent + 1 / PRESETS[self.preset][2] - time.monotonic()))
        found = self.display.frame(self._seen, timeout_s)
        if found is None:
            return None
        self._seen, pixels, width, height = found
        longest, quality, _rate = PRESETS[self.preset]
        picture = Image.frombuffer("RGB", (width, height), pixels, "raw", "BGRX", 0, 1)
        out_w, out_h = fit(width, height, longest)
        if (out_w, out_h) != (width, height):
            picture = picture.resize((out_w, out_h), Image.BILINEAR)
        import io
        kept = io.BytesIO()
        picture.save(kept, "JPEG", quality=quality)
        self._sent = time.monotonic()
        return kept.getvalue()

    def stop(self):
        pass


class PipedSource:
    """Capture with explicit process environment; never change daemon X auth."""
    def __init__(self, description, env, capacity=1):
        import queue
        self.description, self.env = description, env
        self.queue = queue.Queue(capacity)
        self.proc = None
        self.thread = None

    def start(self):
        import subprocess
        import sys
        import threading
        from pathlib import Path
        self.proc = subprocess.Popen([sys.executable, str(Path(__file__).with_name("capture_worker.py")), self.description],
                                     env=self.env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()
        return True

    def _read(self):
        import struct
        import queue
        while True:
            header = self.proc.stdout.read(4)
            if len(header) != 4:
                break
            length = struct.unpack("!I", header)[0]
            if not 0 < length <= 64 * 1024 * 1024:
                break
            data = self.proc.stdout.read(length)
            if len(data) != length:
                break
            try:
                self.queue.put_nowait(data)
            except queue.Full:
                try:
                    self.queue.get_nowait()
                except queue.Empty:
                    pass
                self.queue.put_nowait(data)

    def pull(self, timeout_s):
        import queue
        try:
            return self.queue.get(timeout=timeout_s)
        except queue.Empty:
            return None

    def stop(self):
        import subprocess
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
            if self.thread:
                self.thread.join(timeout=3)
            self.proc.stdout.close()
