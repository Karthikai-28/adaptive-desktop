"""libfreenect synchronous C API behind a killable worker process.

Using ctypes avoids relying on abandoned Python 2-era freenect wheels. No
hand-copied device-struct ABI and no guessed focal length are used.
"""
from __future__ import annotations
import ctypes as ct
import ctypes.util
import multiprocessing as mp
import time
import numpy as np
from .geometry import Intrinsics, median_depth

WIDTH, HEIGHT = 640, 480
FREENECT_DEPTH_MM = 5


def library_path():
    return ctypes.util.find_library("freenect_sync")


class _Native:
    def __init__(self, index: int):
        name = library_path()
        if not name:
            raise RuntimeError("libfreenect_sync not found. Install libfreenect-dev and libfreenect-bin, then run ldconfig if built from source.")
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
