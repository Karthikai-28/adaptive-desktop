"""Adaptive Link - the phone's screen, in a window on the computer.

The other way round from media.py. The phone records its own screen (after
Android has asked its owner, as it does every time) and sends it as video;
the computer shows it in a window (phone_window.py), and what is clicked,
dragged and typed in that window is sent back for the phone to do to itself.

As with the computer's screen, only the offer and the answer touch the link;
the pictures travel on a connection of their own between the two.

Frames are handed to the window as they are decoded, newest only: a window
that cannot keep up shows a lower frame rate, never a growing delay.
"""

import asyncio
import json
import struct
import sys
from pathlib import Path

import rtc  # noqa: F401 - puts the peer-to-peer library on the path

from aiortc import RTCPeerConnection, RTCSessionDescription  # noqa: E402
from aiortc.mediastreams import MediaStreamError  # noqa: E402

WINDOW = Path(__file__).with_name("phone_window.py")
MAX_SIDE = 4096
# What the window may ask of the phone, and what each needs to say.
GESTURES = {"tap": ("x", "y"), "swipe": ("x", "y", "x2", "y2"), "hold": ("x", "y")}
KEYS = ("back", "home", "recents", "notifications", "lock")


def clean_input(event):
    """What the window says was done in it, made fit to send to the phone:
    a tap, a swipe or a long press at places on the screen (0 to 1), one of
    the phone's own keys, or text. Anything else is nothing."""
    if not isinstance(event, dict):
        return None
    kind = event.get("t")
    if kind in GESTURES:
        try:
            given = {name: float(event[name]) for name in GESTURES[kind]}
        except (KeyError, TypeError, ValueError):
            return None
        if any(value != value for value in given.values()):   # not a number: nowhere on the screen
            return None
        places = {name: max(0.0, min(1.0, value)) for name, value in given.items()}
        if kind == "swipe":
            try:
                places["ms"] = max(50, min(3000, int(event.get("ms", 300))))
            except (TypeError, ValueError):
                places["ms"] = 300
        return {"t": kind, **places}
    if kind == "key" and event.get("k") in KEYS:
        return {"t": "key", "k": event["k"]}
    if kind == "text" and isinstance(event.get("s"), str) and event["s"]:
        return {"t": "text", "s": event["s"][:2000]}
    return None


class PhoneScreen:
    """One phone's screen being shown. `on_input` is given what is done in
    the window, already cleaned; `on_closed` is called when it ends from
    either side."""

    def __init__(self, relay=None, on_input=None, on_closed=None, show=True):
        self.relay = relay
        self._on_input = on_input or (lambda _event: None)
        self._on_closed = on_closed or (lambda: None)
        self._show = show
        self._peer = None
        self._window = None
        self._tasks = []
        self.frames = 0
        self.size = (0, 0)
        self.name = ""

    @property
    def showing(self):
        return self._peer is not None

    async def answer(self, offer_sdp, name=""):
        if not isinstance(offer_sdp, str) or not 0 < len(offer_sdp) <= rtc.SDP_MAX or "m=video" not in offer_sdp:
            raise ValueError("not an offer of video")
        await self.close()
        self.name = name
        self.frames = 0
        peer = RTCPeerConnection(rtc.configuration(relay=self.relay))
        self._peer = peer

        @peer.on("track")
        def arrived(track):
            if track.kind == "video":
                self._tasks.append(asyncio.ensure_future(self._draw(track)))

        @peer.on("connectionstatechange")
        async def changed():
            if peer.connectionState in ("failed", "closed", "disconnected") and self._peer is peer:
                await self.close()

        await peer.setRemoteDescription(RTCSessionDescription(sdp=offer_sdp, type="offer"))
        await peer.setLocalDescription(await peer.createAnswer())
        return peer.localDescription.sdp

    async def _open_window(self):
        self._window = await asyncio.create_subprocess_exec(
            sys.executable, str(WINDOW), self.name or "Phone",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        self._tasks.append(asyncio.ensure_future(self._listen(self._window)))

    async def _listen(self, window):
        """What is done in the window, a line at a time, until it is closed."""
        while True:
            line = await window.stdout.readline()
            if not line:
                break
            try:
                event = clean_input(json.loads(line))
            except ValueError:
                continue
            if event:
                self._on_input(event)
        if self._window is window:
            await self.close()   # the window was closed: stop the phone sending

    async def _draw(self, track):
        try:
            while True:
                frame = await track.recv()
                if not 0 < frame.width <= MAX_SIDE or not 0 < frame.height <= MAX_SIDE:
                    continue
                self.frames += 1
                self.size = (frame.width, frame.height)
                if not self._show:
                    continue
                if self._window is None:
                    await self._open_window()
                window = self._window
                # Behind: this picture is dropped rather than queued.
                if window.returncode is not None or window.stdin.transport.get_write_buffer_size() > 0:
                    continue
                picture = frame.reformat(format="rgb24")
                plane = picture.planes[0]
                data = bytes(plane)
                if plane.line_size != frame.width * 3:
                    data = b"".join(data[row * plane.line_size:row * plane.line_size + frame.width * 3]
                                    for row in range(frame.height))
                window.stdin.write(struct.pack("<II", frame.width, frame.height) + data)
        except (MediaStreamError, ConnectionError, BrokenPipeError, asyncio.CancelledError):
            pass

    async def close(self):
        peer, self._peer = self._peer, None
        window, self._window = self._window, None
        tasks, self._tasks = self._tasks, []
        was_showing = peer is not None
        for task in tasks:
            if task is not asyncio.current_task():
                task.cancel()
        if window is not None and window.returncode is None:
            try:
                window.terminate()
            except ProcessLookupError:
                pass
        if peer is not None:
            try:
                await peer.close()
            except Exception:  # noqa: BLE001 - it is being thrown away
                pass
        if was_showing:
            self._on_closed()
