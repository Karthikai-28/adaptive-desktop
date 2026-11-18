"""The Kinect's latest frame in shared memory: written by the hub, read by Air (and anything else).

libfreenect lets one process open the Kinect. The hub (kinect_hub.py) is that process; it puts
every frame here, so gestures, Kinect Studio and the virtual webcam all see the same camera.

    /dev/shm/adaptive-kinect-<uid>     mode 0600, only this user
    header (256 bytes), then the picture (640x480x3 RGB) and depth (640x480 uint16, millimetres,
    registered to the picture; 0 = no reading)

A sequence lock keeps a reader from seeing half a frame: the writer makes `seq` odd, writes,
then makes it even; a reader copies only between two equal, even reads of `seq`. Readers write
`client_seen` (a time) so the hub knows it is still needed. Pure stdlib + numpy.

`epoch` counts the hub's switches between colour and infrared: the picture's geometry (and the
depth's: registered to colour, or the infrared camera's own) is the same for every frame of one
epoch. A reader that needs one geometry (the scanner, a tracker's memory of where people were)
compares epochs, not only modes.

`Snapshot` is one frame as the hub keeps it in memory: picture, depth, mode, the lens numbers
for that mode, sequence, capture times and epoch together, taken under one lock, so nothing
pairs a picture with another frame's mode or lens.
"""

import mmap
import os
import struct
import time
from pathlib import Path

W, H = 640, 480
RGB_BYTES = W * H * 3
DEPTH_BYTES = W * H * 2
HEADER = 256
SIZE = HEADER + RGB_BYTES + DEPTH_BYTES
MAGIC = b"AKF2"

# magic, seq, t, mode (0 rgb, 1 ir), ax, ay, az, tilt, fps, frames, client_seen, epoch
_FMT = "<4sQdIhhhfdQdI"
_SEQ_AT = 4
_SEEN_AT = struct.calcsize("<4sQdIhhhfdQ")


class Snapshot:
    """One frame and everything needed to interpret it (see the module notes)."""

    __slots__ = ("rgb", "depth", "mode", "intrinsics", "seq", "captured", "mono", "accel",
                 "epoch", "stamps")

    def __init__(self, rgb, depth, mode, intrinsics, seq, captured, mono, accel=(0, 0, 0),
                 epoch=0, stamps=None):
        self.rgb, self.depth, self.mode, self.intrinsics = rgb, depth, mode, tuple(intrinsics)
        self.seq, self.captured, self.mono = seq, captured, mono
        self.accel, self.epoch, self.stamps = tuple(accel), epoch, stamps

    def meta(self):
        """The frame's description without its pixels (for /api/people and the page)."""
        return {"frame": self.seq, "mode": self.mode, "epoch": self.epoch,
                "intrinsics": [round(float(v), 3) for v in self.intrinsics],
                "captured": round(self.captured, 4), "size": [W, H]}


def path():
    return Path(os.environ.get("AIR_FRAMES", f"/dev/shm/adaptive-kinect-{os.getuid()}"))


class Writer:
    def __init__(self, where=None):
        self.path = Path(where or path())
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            os.ftruncate(fd, SIZE)
            self._mm = mmap.mmap(fd, SIZE)
        finally:
            os.close(fd)
        self._mm[:4] = MAGIC
        self.seq = 0
        self.frames = 0
        struct.pack_into("<Q", self._mm, _SEQ_AT, 0)

    def write(self, rgb, depth, mode="rgb", accel=(0, 0, 0), tilt=0.0, fps=0.0, epoch=0):
        mm = self._mm
        self.seq += 1                                 # odd: writing
        struct.pack_into("<Q", mm, _SEQ_AT, self.seq)
        mm[HEADER:HEADER + RGB_BYTES] = rgb.tobytes()
        mm[HEADER + RGB_BYTES:SIZE] = depth.tobytes()
        self.frames += 1
        seen = struct.unpack_from("<d", mm, _SEEN_AT)[0]
        struct.pack_into(_FMT, mm, 0, MAGIC, self.seq, time.monotonic(), 1 if mode == "ir" else 0,
                         int(accel[0]), int(accel[1]), int(accel[2]), float(tilt or 0.0),
                         float(fps), self.frames, seen, int(epoch) & 0xFFFFFFFF)
        self.seq += 1                                 # even: done
        struct.pack_into("<Q", mm, _SEQ_AT, self.seq)

    def client_seen(self):
        return struct.unpack_from("<d", self._mm, _SEEN_AT)[0]

    def close(self, unlink=True):
        self._mm.close()
        if unlink:
            try:
                self.path.unlink()
            except OSError:
                pass


class Reader:
    def __init__(self, where=None):
        self.path = Path(where or path())
        fd = os.open(self.path, os.O_RDWR)
        try:
            if os.fstat(fd).st_size < SIZE:
                raise OSError("Kinect frames not ready")
            self._mm = mmap.mmap(fd, SIZE)
        finally:
            os.close(fd)
        if self._mm[:4] != MAGIC:
            raise OSError("not a Kinect frame store")
        self.last = 0

    def header(self):
        magic, seq, t, mode, ax, ay, az, tilt, fps, frames, seen, epoch = struct.unpack_from(
            _FMT, self._mm, 0)
        return {"seq": seq, "t": t, "mode": "ir" if mode else "rgb", "accel": [ax, ay, az],
                "tilt": tilt, "fps": fps, "frames": frames, "epoch": epoch}

    def read(self, timeout=1.0, newer=True):
        """(rgb, depth, header) of a frame newer than the last one read; OSError on timeout."""
        import numpy as np
        mm = self._mm
        deadline = time.monotonic() + timeout
        struct.pack_into("<d", mm, _SEEN_AT, time.monotonic())
        while True:
            s1 = struct.unpack_from("<Q", mm, _SEQ_AT)[0]
            if s1 % 2 == 0 and s1 and (not newer or s1 != self.last):
                rgb = np.frombuffer(mm[HEADER:HEADER + RGB_BYTES], np.uint8).reshape(H, W, 3)
                depth = np.frombuffer(mm[HEADER + RGB_BYTES:SIZE], np.uint16).reshape(H, W)
                head = self.header()
                if struct.unpack_from("<Q", mm, _SEQ_AT)[0] == s1:
                    self.last = s1
                    return rgb, depth, head
            if time.monotonic() > deadline:
                raise OSError("no new Kinect frame")
            time.sleep(0.003)

    def close(self):
        self._mm.close()
