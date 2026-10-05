"""Adaptive Link - the screen as video, with the computer's sound.

The JPEG stream (screen.py) sends every frame whole. This sends video
instead: the two devices set up a media connection (WebRTC, the same library
the direct tunnel uses), the screen is encoded as H.264 or VP8 - which send
only what changed - and what the computer is playing goes with it as Opus.
It takes a fraction of the data, which is what makes the screen usable away
from Wi-Fi.

How the two find each other is the only part that touches the link: the
phone posts its offer to /v1/rtc and gets the answer back, over the same
mutual TLS as every other request. So the media connection can only be set
up by a paired phone, and it is encrypted between the two with keys agreed
in that exchange (DTLS-SRTP). Pointer and keyboard keep going over
/v1/input.

The pictures and the sound come from GStreamer, as in screen.py; the
encoding and the sending are aiortc's.
"""

import asyncio
import fractions
import time

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

import rtc  # noqa: E402 - puts the peer-to-peer library on the path
import screen  # noqa: E402

import av  # noqa: E402
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription  # noqa: E402
from aiortc.mediastreams import MediaStreamError  # noqa: E402

Gst.init(None)

PRESETS = {
    # name: (longest side in pixels, frames per second)
    "low": (960, 10),
    "medium": (1280, 15),
    "high": (1920, 20),
}
VIDEO_CLOCK = 90000
AUDIO_RATE = 48000
AUDIO_SAMPLES = 960                     # 20 ms, what Opus is given at a time
AUDIO_CHUNK = AUDIO_SAMPLES * 2 * 2     # stereo, 16 bits
MAX_VIEWERS = 3


def frame_size(width, height, preset):
    """(w, h, frames per second) for a preset: fitted to the longest side,
    the width a multiple of 16 so each row of the picture is its own width
    in memory with nothing added to it."""
    longest, rate = PRESETS.get(preset, PRESETS["medium"])
    out_w, out_h = screen.fit(width, height, longest)
    return max(16, out_w // 16 * 16), out_h, rate


def video_pipeline(width, height, preset, region=None):
    if region:
        width, height = region[2], region[3]
    out_w, out_h, rate = frame_size(width, height, preset)
    return (
        screen.source(region)
        + f"! video/x-raw,framerate={rate}/1 "
        "! videoscale method=bilinear "
        f"! video/x-raw,width={out_w},height={out_h} "
        "! videoconvert "
        "! video/x-raw,format=I420 "
        "! appsink name=sink max-buffers=1 drop=true sync=false emit-signals=false"
    )


AUDIO_PIPELINE = (
    # What the computer is playing: the "monitor" of where its sound goes.
    "pulsesrc device=@DEFAULT_MONITOR@ "
    f"! audio/x-raw,format=S16LE,rate={AUDIO_RATE},channels=2 "
    "! appsink name=sink max-buffers=50 drop=true sync=false emit-signals=false"
)


def _pull(sink, timeout_s):
    """The next buffer from a pipeline's end as bytes, or None. Blocking."""
    sample = sink.emit("try-pull-sample", int(timeout_s * Gst.SECOND))
    if sample is None:
        return None
    buffer = sample.get_buffer()
    ok, info = buffer.map(Gst.MapFlags.READ)
    if not ok:
        return None
    try:
        return bytes(info.data)
    finally:
        buffer.unmap(info)


def _fill(plane, data, width, height):
    """Put one plane of a picture into a frame. The frame may keep each row
    longer than the picture is wide; then the rows are laid in one by one."""
    if plane.line_size == width:
        plane.update(data)
        return
    padded = bytearray(plane.line_size * height)
    for row in range(height):
        padded[row * plane.line_size:row * plane.line_size + width] = data[row * width:(row + 1) * width]
    plane.update(bytes(padded))


class _Source(MediaStreamTrack):
    """A track fed by a GStreamer pipeline that ends in an appsink."""

    description = ""

    def __init__(self):
        super().__init__()
        self._pipeline = None
        self._sink = None

    def start(self):
        """Start the pipeline. Returns whether it is running."""
        try:
            self._pipeline = Gst.parse_launch(self.description)
        except Exception:  # noqa: BLE001 - GLib raises its own error for a pipeline it cannot build
            return False
        self._sink = self._pipeline.get_by_name("sink")
        self._pipeline.set_state(Gst.State.PLAYING)
        # Wait to see whether it really starts: a source that is not there
        # (no sound server) fails here rather than on the first frame.
        state = self._pipeline.get_state(3 * Gst.SECOND)
        if state[0] == Gst.StateChangeReturn.FAILURE:
            self.stop()
            return False
        return True

    def stop(self):
        super().stop()
        if self._pipeline is not None:
            self._pipeline.set_state(Gst.State.NULL)
            self._pipeline = None
            self._sink = None


class ScreenTrack(_Source):
    kind = "video"

    def __init__(self, screen_size, preset, region=None):
        super().__init__()
        self.width, self.height, self.rate = frame_size(*(region[2:] if region else screen_size), preset)
        self.description = video_pipeline(*screen_size, preset, region)
        self._started = time.monotonic()

    async def recv(self):
        while True:
            if self.readyState != "live" or self._sink is None:
                raise MediaStreamError
            data = await asyncio.to_thread(_pull, self._sink, 1.0)
            if data is not None and len(data) >= self.width * self.height * 3 // 2:
                break
        frame = av.VideoFrame(self.width, self.height, "yuv420p")
        luma, chroma = self.width * self.height, (self.width // 2) * (self.height // 2)
        _fill(frame.planes[0], data[:luma], self.width, self.height)
        _fill(frame.planes[1], data[luma:luma + chroma], self.width // 2, self.height // 2)
        _fill(frame.planes[2], data[luma + chroma:luma + 2 * chroma], self.width // 2, self.height // 2)
        frame.pts = int((time.monotonic() - self._started) * VIDEO_CLOCK)
        frame.time_base = fractions.Fraction(1, VIDEO_CLOCK)
        return frame


class MadeTrack(MediaStreamTrack):
    """The picture of a display made for a phone, from the frames the display
    itself was given (virtual_display.py) - not captured a second time from
    the screen. A frame is sent when the display changed, and the last one
    again each second when it did not, so a phone that joins late or lost a
    packet is not left waiting for a change to see anything."""

    kind = "video"
    AGAIN_S = 1.0

    def __init__(self, display, preset):
        super().__init__()
        self.display = display
        _longest, self.rate = PRESETS.get(preset, PRESETS["medium"])
        self.preset = preset
        found = display.frame(-1, 2.0)
        source = found[2:] if found else (1280, 720)
        self.width, self.height, _ = frame_size(*source, preset)
        self._seen = -1
        self._last = None
        self._sent = 0.0
        self._started = time.monotonic()

    def start(self):
        return True

    async def recv(self):
        while True:
            if self.readyState != "live":
                raise MediaStreamError
            # At the preset's rate at most.
            await asyncio.sleep(max(0.0, self._sent + 1 / self.rate - time.monotonic()))
            found = await asyncio.to_thread(self.display.frame, self._seen, self.AGAIN_S)
            if found is not None:
                self._seen, pixels, width, height = found
                import numpy

                whole = av.VideoFrame.from_ndarray(numpy.frombuffer(pixels, numpy.uint8).reshape(height, width, 4),
                                                   format="bgra")
                self._last = whole.reformat(width=self.width, height=self.height, format="yuv420p")
            if self._last is not None:
                break
        self._sent = time.monotonic()
        frame = self._last
        frame.pts = int((self._sent - self._started) * VIDEO_CLOCK)
        frame.time_base = fractions.Fraction(1, VIDEO_CLOCK)
        return frame


class SoundTrack(_Source):
    kind = "audio"
    description = AUDIO_PIPELINE

    def __init__(self):
        super().__init__()
        self._waiting = b""
        self._sent = 0

    async def recv(self):
        while len(self._waiting) < AUDIO_CHUNK:
            if self.readyState != "live" or self._sink is None:
                raise MediaStreamError
            data = await asyncio.to_thread(_pull, self._sink, 1.0)
            if data:
                self._waiting += data
        chunk, self._waiting = self._waiting[:AUDIO_CHUNK], self._waiting[AUDIO_CHUNK:]
        frame = av.AudioFrame(format="s16", layout="stereo", samples=AUDIO_SAMPLES)
        frame.planes[0].update(chunk)
        frame.sample_rate = AUDIO_RATE
        frame.pts = self._sent
        frame.time_base = fractions.Fraction(1, AUDIO_RATE)
        self._sent += AUDIO_SAMPLES
        return frame


class MediaServer:
    """The computer's end of the screen as video: one connection per phone
    that is watching, each with its own capture."""

    def __init__(self, relay=None, report=None):
        self.relay = relay
        self._watching = {}
        self._next = 1
        self._report = report or (lambda _what: None)

    @property
    def viewers(self):
        return len(self._watching)

    async def answer(self, offer_sdp, screen_size, preset="medium", sound=True, region=None, made=None):
        """Start sending the screen to the phone that made this offer.
        Returns {"id", "answer", "sound", "size"}; raises ValueError for an
        offer that is not one."""
        if not isinstance(offer_sdp, str) or not 0 < len(offer_sdp) <= rtc.SDP_MAX or "m=video" not in offer_sdp:
            raise ValueError("not an offer for video")
        while len(self._watching) >= MAX_VIEWERS:
            await self.close(next(iter(self._watching)))

        peer = RTCPeerConnection(rtc.configuration(relay=self.relay))
        session = self._next
        self._next += 1
        # A display made for a phone sends what it was given; any other, what
        # is captured from the screen.
        picture = (await asyncio.to_thread(MadeTrack, made, preset)) if made is not None \
            else ScreenTrack(screen_size, preset, region)
        voice = SoundTrack() if sound and "m=audio" in offer_sdp else None
        if not await asyncio.to_thread(picture.start):
            await peer.close()
            raise ValueError("the screen could not be captured")
        if voice is not None and not await asyncio.to_thread(voice.start):
            voice = None   # no sound server to listen to: the picture goes alone
        self._watching[session] = (peer, picture, voice)

        @peer.on("connectionstatechange")
        async def changed():
            if peer.connectionState in ("connected", "failed"):
                self._report(f"video {peer.connectionState}")
            if peer.connectionState in ("failed", "closed", "disconnected"):
                await self.close(session)

        try:
            # Which codec is used is the phone's to say, by the order in its
            # offer: H.264 where it decodes that in hardware, VP8 otherwise.
            await peer.setRemoteDescription(RTCSessionDescription(sdp=offer_sdp, type="offer"))
            peer.addTrack(picture)
            if voice is not None:
                peer.addTrack(voice)
            await peer.setLocalDescription(await peer.createAnswer())
        except Exception:
            await self.close(session)
            raise
        return {"id": session, "answer": peer.localDescription.sdp, "sound": voice is not None,
                "size": [picture.width, picture.height]}

    async def close(self, session):
        found = self._watching.pop(session, None)
        if found is None:
            return False
        peer, picture, voice = found
        for track in (picture, voice):
            if track is not None:
                await asyncio.to_thread(track.stop)
        try:
            await peer.close()
        except Exception:  # noqa: BLE001 - it is being thrown away
            pass
        return True

    async def close_all(self):
        for session in list(self._watching):
            await self.close(session)
