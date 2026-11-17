"""libfreenect synchronous C API behind a killable worker process.

Using ctypes avoids relying on abandoned Python 2-era freenect wheels. No
hand-copied device-struct ABI and no guessed focal length are used.
"""
from __future__ import annotations
import ctypes as ct
import ctypes.util
import multiprocessing as mp
import os
import subprocess
import sys
import time
from pathlib import Path
import numpy as np
from .geometry import Intrinsics, median_depth

WIDTH, HEIGHT = 640, 480
FREENECT_DEPTH_MM = 5


# This package lives in Adaptive Desktop's kinect/ folder; the repo's own libfreenect build
# (kinect/build-libfreenect.sh -> .local/libfreenect) is used first, then the system's.
REPO = Path(__file__).resolve().parents[4]
LOCAL_SYNC = REPO / ".local/libfreenect/lib/libfreenect_sync.so"


def library_path():
    env = os.environ.get("KINECTSCAN_FREENECT")
    if env:
        return env
    if LOCAL_SYNC.is_file():
        return str(LOCAL_SYNC)
    return ctypes.util.find_library("freenect_sync")


class _Native:
    def __init__(self, index: int):
        name = library_path()
        if not name:
            raise RuntimeError("libfreenect_sync not found. Install libfreenect-dev and libfreenect-bin, then run ldconfig if built from source.")
        core = Path(name).with_name("libfreenect.so")
        if "/" in name and core.is_file():
            ct.CDLL(str(core), mode=ct.RTLD_GLOBAL)   # the private build's own core library
        self.lib = ct.CDLL(name)
        self.index = int(index)
        self.lib.freenect_sync_get_depth.argtypes = [ct.POINTER(ct.c_void_p),ct.POINTER(ct.c_uint32),ct.c_int,ct.c_int]
        self.lib.freenect_sync_get_depth.restype = ct.c_int
        self.lib.freenect_sync_stop.argtypes = []
        self.lib.freenect_sync_stop.restype = None

    def read(self):
        ptr = ct.c_void_p(); stamp = ct.c_uint32()
        rc = self.lib.freenect_sync_get_depth(ct.byref(ptr),ct.byref(stamp),self.index,FREENECT_DEPTH_MM)
        if rc != 0 or not ptr.value:
            raise RuntimeError(f"Kinect depth read failed ({rc}). Check external power, USB, udev permissions and other camera applications.")
        # Own the memory before requesting another frame; the native ring buffer is reused.
        data = np.ctypeslib.as_array(ct.cast(ptr,ct.POINTER(ct.c_uint16)),shape=(HEIGHT*WIDTH,)).reshape(HEIGHT,WIDTH).copy()
        data[(data == 0) | (data >= 10000)] = 0
        return data, int(stamp.value)

    def intrinsics(self):
        if not hasattr(self.lib,"freenect_sync_camera_to_world"):
            raise RuntimeError("This libfreenect lacks freenect_sync_camera_to_world. Supply independently calibrated --intrinsics JSON, or build a newer official libfreenect. No guessed intrinsics will be substituted.")
        f = self.lib.freenect_sync_camera_to_world
        f.argtypes = [ct.c_int,ct.c_int,ct.c_int,ct.POINTER(ct.c_double),ct.POINTER(ct.c_double),ct.c_int]
        f.restype = ct.c_int
        def world(u,v):
            x,y = ct.c_double(),ct.c_double()
            if f(u,v,1000,ct.byref(x),ct.byref(y),self.index) != 0:
                raise RuntimeError("Factory projection query failed")
            return x.value,y.value
        x0,y0 = world(320,240); x1,y1 = world(321,241)
        if abs(x1-x0)<1e-9 or abs(y1-y0)<1e-9:
            raise RuntimeError("Invalid factory ray mapping")
        fx,fy = 1000/(x1-x0),1000/(y1-y0)
        cx,cy = 320-x0*fx/1000,240-y0*fy/1000
        return Intrinsics(WIDTH,HEIGHT,fx,fy,cx,cy,
            source="libfreenect device-specific factory camera_to_world model; not independent metrology calibration")

    def close(self):
        self.lib.freenect_sync_stop()


def _worker(conn,index,override):
    native = None
    try:
        native = _Native(index)
        native.read()  # Initializes the device / factory registration.
        k = Intrinsics.from_dict(override) if override else native.intrinsics()
        if (k.width,k.height)!=(WIDTH,HEIGHT):
            raise ValueError("Kinect medium mode requires 640x480 IR intrinsics")
        conn.send(("ready",k.to_dict()))
        while True:
            cmd = conn.recv()
            if cmd == "stop": break
            if cmd != "read": raise ValueError("Unknown acquisition command")
            depth,stamp = native.read()
            conn.send(("frame",depth,stamp,time.monotonic()))
    except (EOFError,BrokenPipeError):
        pass
    except BaseException as exc:
        try: conn.send(("error",f"{type(exc).__name__}: {exc}"))
        except (BrokenPipeError,EOFError,OSError): pass
    finally:
        if native is not None:
            native.close()
        conn.close()


class KinectCapture:
    """One process owns one sensor. Reads time out instead of hanging the CLI."""
    def __init__(self,index=0,timeout=10.,intrinsics=None):
        if index < 0 or timeout <= 0: raise ValueError("Invalid device index or timeout")
        self.index=index; self.timeout=timeout; self.override=intrinsics
        self.process=None; self.conn=None; self.k=None; self.last_timestamp=None

    def __enter__(self):
        ctx=mp.get_context("spawn"); parent,child=ctx.Pipe()
        self.conn=parent
        self.process=ctx.Process(target=_worker,args=(child,self.index,
            self.override.to_dict() if self.override else None),daemon=True)
        self.process.start(); child.close()
        try:
            msg=self._receive()
            if msg[0]!="ready": raise RuntimeError(f"Unexpected worker reply: {msg[0]}")
            self.k=Intrinsics.from_dict(msg[1])
            return self
        except BaseException:
            self.close(); raise

    def _receive(self):
        if not self.conn.poll(self.timeout):
            raise TimeoutError("Kinect worker timed out. Check power, permissions and USB. The worker will be terminated on exit.")
        try: msg=self.conn.recv()
        except EOFError as exc: raise RuntimeError("Kinect worker exited unexpectedly") from exc
        if msg[0]=="error": raise RuntimeError(msg[1])
        return msg

    def read(self):
        for _ in range(5):
            self.conn.send("read"); msg=self._receive()
            if msg[0]!="frame": raise RuntimeError("Unexpected capture reply")
            depth,stamp,host=msg[1:]
            if stamp!=self.last_timestamp:
                self.last_timestamp=stamp
                return depth,stamp,host
        raise RuntimeError("Repeated device timestamp: no fresh depth frames")

    def median(self,samples=15,max_std_mm=None):
        if not 1 <= samples <= 120: raise ValueError("samples must be 1..120")
        frames=[]
        for _ in range(samples):
            depth,stamp,host=self.read(); frames.append(depth)
        return median_depth(frames,max_std_mm=max_std_mm),stamp,host

    def close(self):
        if self.conn is not None:
            try: self.conn.send("stop")
            except (BrokenPipeError,EOFError,OSError): pass
        if self.process is not None:
            self.process.join(timeout=1.)
            if self.process.is_alive():
                self.process.terminate(); self.process.join(timeout=2.)
            if self.process.is_alive():
                self.process.kill(); self.process.join(timeout=1.)
        if self.conn is not None: self.conn.close()
        self.process=None; self.conn=None

    def __exit__(self,*exc):
        self.close()


# -- the Adaptive Desktop Kinect hub ------------------------------------------------------------
# The hub (services/adaptive-air/kinect_hub.py) is the one process that opens the Kinect; Air,
# Kinect Studio, Kinect Motion and this scanner all read its frames from shared memory, so a scan
# works while the others run. Its depth is millimetres: in the infrared camera's geometry when the
# hub shows infrared, registered to the colour camera when it shows colour.

HUB_UNIT = "adaptive-kinect.service"
NOMINAL = {"rgb": (525.0, 525.0, 319.5, 239.5), "ir": (575.8, 575.8, 314.5, 235.5)}   # kinect.INTRINSICS


def hub_running():
    """Is the hub's frame store there and fresh?"""
    try:
        frames = _hub_frames()
        r = frames.Reader()
        try:
            # The hub stamps frames with the system-wide monotonic clock.
            return time.monotonic() - r.header()["t"] < 3.0
        finally:
            r.close()
    except (OSError, ImportError):
        return False


def _hub_frames():
    air = REPO / "services/adaptive-air"
    if str(air) not in sys.path:
        sys.path.insert(0, str(air))
    import frames
    return frames


class HubCapture:
    """The KinectCapture interface over the hub's shared frames. Every frame of one session is in
    one camera geometry: frames in the other picture (the hub switches colour/infrared with the
    room's light) are skipped, never mixed."""

    def __init__(self, timeout=10., intrinsics=None):
        self.timeout, self.override = timeout, intrinsics
        self.reader = None
        self.k = None
        self.mode = None
        self.skipped = 0
        self.last_timestamp = None

    def __enter__(self):
        frames = _hub_frames()
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self.reader = frames.Reader()
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise TimeoutError("The Kinect hub did not start (systemctl --user status adaptive-kinect)")
                subprocess.run(["systemctl", "--user", "start", HUB_UNIT], capture_output=True)
                time.sleep(0.3)
        _, _, head = self.reader.read(timeout=self.timeout)
        self.mode = head["mode"]
        if self.override is not None:
            self.k = self.override
        else:
            fx, fy, cx, cy = NOMINAL[self.mode]
            self.k = Intrinsics(WIDTH, HEIGHT, fx, fy, cx, cy,
                source=f"Kinect hub, {self.mode} picture: nominal Kinect v1 lens values, not this device's "
                       "factory calibration (stop the hub and run `kinectscan probe` for that)")
        return self

    def read(self):
        deadline = time.monotonic() + self.timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError(f"No {self.mode} frame from the Kinect hub (it may have switched picture)")
            _, depth, head = self.reader.read(timeout=left)
            if head["mode"] != self.mode:
                self.skipped += 1
                continue
            data = depth.copy()
            data[(data == 0) | (data >= 10000)] = 0
            self.last_timestamp = head["seq"]
            return data, int(head["seq"]), time.monotonic()

    def median(self, samples=15, max_std_mm=None):
        if not 1 <= samples <= 120:
            raise ValueError("samples must be 1..120")
        got = [self.read() for _ in range(samples)]
        return median_depth([d for d, _, _ in got], max_std_mm=max_std_mm), got[-1][1], got[-1][2]

    def close(self):
        if self.reader is not None:
            self.reader.close()
            self.reader = None

    def __exit__(self, *exc):
        self.close()


def open_capture(source="auto", index=0, timeout=10., intrinsics=None):
    """The hub when it runs (or when asked), otherwise libfreenect directly."""
    if source == "hub" or (source == "auto" and hub_running()):
        return HubCapture(timeout=timeout, intrinsics=intrinsics)
    return KinectCapture(index=index, timeout=timeout, intrinsics=intrinsics)
