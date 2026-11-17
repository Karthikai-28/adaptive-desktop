"""The Kinect v1 ("Kinect for Xbox 360") through libfreenect, with ctypes.

Air does not use libfreenect's Cython wrapper: the C library and its "sync" wrapper are built by
kinect/build-libfreenect.sh into .local/libfreenect and loaded here. Two ways in:

    Motor   the tilt motor, the LED and the accelerometer, straight over libusb (libfreenect
            only opens a Kinect whose camera is on USB). Works on USB power alone.
    Camera  colour (640x480 RGB) and depth registered to it (millimetres, aligned pixel for pixel
            with the colour picture), or infrared and depth in the infrared camera's own geometry
            (the depth camera is the infrared camera), through the sync API. Needs the 12 V supply.

The colour and infrared pictures share one USB stream: the Kinect v1 gives one or the other,
never both at once (switching takes ~0.3 s). Depth comes alongside either.

probe() reads sysfs only and never opens the device, so it is safe to call any time.
"""

import ctypes
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LIB_DIR = Path(os.environ.get("AIR_LIBFREENECT", REPO / ".local/libfreenect/lib"))

VENDOR = "045e"
# Product ids of the three USB devices behind the Kinect's internal hub, per model.
PARTS = {
    "1414": {"motor": "02b0", "audio": "02ad", "camera": "02ae"},
    "1473": {"motor": "02c2", "audio": "02bb", "camera": "02bf"},
    "kinect-for-windows": {"motor": "02c2", "audio": "02be", "camera": "02bf"},
}

WIDTH, HEIGHT = 640, 480

# libfreenect.h enums
VIDEO_RGB = 0
DEPTH_REGISTERED = 4          # millimetres, registered to the RGB image; 0 = no reading
DEPTH_MM = 5                  # millimetres, in the depth (= infrared) camera's own geometry
# Pinhole intrinsics (fx, fy, cx, cy) of the picture each mode gives, 640x480. Colour: the RGB
# camera (depth registered to it). Infrared: the IR/depth camera (the usual Kinect v1 values).
INTRINSICS = {"rgb": (525.0, 525.0, 319.5, 239.5), "ir": (575.8, 575.8, 314.5, 235.5)}


def intrinsics(mode="rgb"):
    return INTRINSICS.get(mode, INTRINSICS["rgb"])


LED = {"off": 0, "green": 1, "red": 2, "yellow": 3, "blink-green": 4, "blink-red-yellow": 6}


def probe(sysfs="/sys/bus/usb/devices"):
    """What of a Kinect is on USB, from sysfs alone.

    Returns {"present", "model", "motor", "camera", "audio", "advice"}. Only the motor showing
    is the Kinect without its 12 V supply: USB powers the hub and motor, not the camera.
    """
    found = set()
    root = Path(sysfs)
    try:
        entries = list(root.iterdir())
    except OSError:
        entries = []
    for entry in entries:
        try:
            vendor = (entry / "idVendor").read_text().strip()
            product = (entry / "idProduct").read_text().strip()
        except OSError:
            continue
        if vendor == VENDOR:
            found.add(product)
    model = None
    for name, parts in PARTS.items():
        if parts["motor"] in found or parts["camera"] in found:
            model = name
            break
    parts = PARTS.get(model, {})
    state = {
        "present": model is not None,
        "model": model,
        "motor": parts.get("motor") in found,
        "camera": parts.get("camera") in found,
        "audio": parts.get("audio") in found,
    }
    if not state["present"]:
        state["advice"] = "No Kinect on USB."
    elif not state["camera"]:
        state["advice"] = ("Only the Kinect's motor is on USB: plug in its 12 V power supply "
                           "(the Kinect's own adapter). USB alone does not power the camera.")
    else:
        state["advice"] = "Kinect camera ready."
    return state


def available():
    """True when the libfreenect libraries Air needs have been built."""
    return (LIB_DIR / "libfreenect.so").exists() and (LIB_DIR / "libfreenect_sync.so").exists()


def _load(name):
    return ctypes.CDLL(str(LIB_DIR / name), mode=ctypes.RTLD_GLOBAL)


class Motor:
    """The tilt motor, LED and accelerometer, spoken to directly over libusb.

    libfreenect only counts a Kinect whose camera is on USB, so it cannot open the motor of a
    Kinect on USB power alone. The motor's protocol is three vendor control requests on endpoint
    0 (no interface is claimed, so this works alongside libfreenect's own handle):
        0x06 LED (wValue = colour)   0x31 tilt (wValue = degrees x 2)   0x32 read state (10 bytes)
    """

    def __init__(self, model=None):
        self._usb = ctypes.CDLL("libusb-1.0.so.0")
        usb = self._usb
        usb.libusb_init.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        usb.libusb_open_device_with_vid_pid.argtypes = [ctypes.c_void_p, ctypes.c_uint16,
                                                        ctypes.c_uint16]
        usb.libusb_open_device_with_vid_pid.restype = ctypes.c_void_p
        usb.libusb_control_transfer.argtypes = [ctypes.c_void_p, ctypes.c_uint8, ctypes.c_uint8,
                                                ctypes.c_uint16, ctypes.c_uint16, ctypes.c_char_p,
                                                ctypes.c_uint16, ctypes.c_uint]
        usb.libusb_close.argtypes = [ctypes.c_void_p]
        usb.libusb_exit.argtypes = [ctypes.c_void_p]
        self._ctx = ctypes.c_void_p()
        self._handle = None
        if usb.libusb_init(ctypes.byref(self._ctx)) < 0:
            raise OSError("libusb could not start")
        models = [model] if model else list(PARTS)
        for name in models:
            handle = usb.libusb_open_device_with_vid_pid(self._ctx, int(VENDOR, 16),
                                                         int(PARTS[name]["motor"], 16))
            if handle:
                self._handle = handle
                break
        if not self._handle:
            self.close()
            raise OSError("could not open the Kinect motor (not on USB, or no permission)")

    def _out(self, request, value):
        return self._usb.libusb_control_transfer(self._handle, 0x40, request, value & 0xFFFF, 0,
                                                 None, 0, 500) >= 0

    def led(self, colour):
        return self._out(0x06, LED[colour])

    def tilt(self, degrees):
        """Tilt to an angle from the horizon, -27..27. The motor itself needs the 12 V supply."""
        return self._out(0x31, int(round(max(-27.0, min(27.0, float(degrees))) * 2)))

    def state(self):
        buf = ctypes.create_string_buffer(10)
        n = self._usb.libusb_control_transfer(self._handle, 0xC0, 0x32, 0, 0, buf, 10, 500)
        if n < 10:
            raise OSError("no state from the Kinect motor")
        return parse_state(buf.raw)

    def close(self):
        if self._handle:
            self._usb.libusb_close(self._handle)
            self._handle = None
        if self._ctx:
            self._usb.libusb_exit(self._ctx)
            self._ctx = ctypes.c_void_p()


def parse_state(raw):
    """The motor's 10-byte state: accelerometer (big-endian int16 x3, ~819 per g), tilt, status."""
    import struct
    ax, ay, az = struct.unpack(">hhh", raw[2:8])
    angle = struct.unpack("b", raw[8:9])[0]
    return {"accel": [ax, ay, az], "tilt": None if angle == -128 else angle / 2.0,
            "status": {0: "stopped", 1: "at-limit", 4: "moving"}.get(raw[9], raw[9])}


class TiltState(ctypes.Structure):
    """libfreenect's freenect_raw_tilt_state."""
    _fields_ = [("accelerometer_x", ctypes.c_int16), ("accelerometer_y", ctypes.c_int16),
                ("accelerometer_z", ctypes.c_int16), ("tilt_angle", ctypes.c_int8),
                ("tilt_status", ctypes.c_int)]


VIDEO_IR_8BIT = 2
IR_HEIGHT = 488               # the IR picture is 640x488; the bottom 8 rows are dropped
COUNTS_PER_G = 819


class Camera:
    """Colour (or infrared) + registered depth through libfreenect's sync API (numpy, copied).

    Every call must come from one thread: the hub's capture loop.
    """

    def __init__(self, index=0):
        import numpy as np
        self._np = np
        _load("libfreenect.so")
        self._lib = _load("libfreenect_sync.so")
        lib = self._lib
        for fn in (lib.freenect_sync_get_video, lib.freenect_sync_get_depth):
            fn.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint32),
                           ctypes.c_int, ctypes.c_int]
        lib.freenect_sync_set_led.argtypes = [ctypes.c_int, ctypes.c_int]
        lib.freenect_sync_set_tilt_degs.argtypes = [ctypes.c_int, ctypes.c_int]
        lib.freenect_sync_get_tilt_state.argtypes = [ctypes.POINTER(ctypes.POINTER(TiltState)),
                                                     ctypes.c_int]
        self.index = index

    def read(self, mode="rgb"):
        """(picture HxWx3 uint8, depth_mm HxW uint16) or raises OSError.

        mode "ir" gives the infrared camera (it sees in the dark, and shows the projector's dot
        pattern) as a grey picture in the same three channels, and depth in that camera's own
        geometry (FREENECT_DEPTH_MM): registering it to the colour camera would put every
        distance a few centimetres beside the infrared picture's hand.
        """
        np = self._np
        ptr, ts = ctypes.c_void_p(), ctypes.c_uint32()
        fmt = VIDEO_IR_8BIT if mode == "ir" else VIDEO_RGB
        if self._lib.freenect_sync_get_video(ctypes.byref(ptr), ctypes.byref(ts), self.index,
                                             fmt) < 0:
            raise OSError("no Kinect picture")
        if mode == "ir":
            ir = np.ctypeslib.as_array((ctypes.c_uint8 * (WIDTH * IR_HEIGHT)).from_address(
                ptr.value)).reshape(IR_HEIGHT, WIDTH)[:HEIGHT]
            rgb = np.repeat(ir[:, :, None], 3, axis=2)
        else:
            rgb = np.ctypeslib.as_array((ctypes.c_uint8 * (WIDTH * HEIGHT * 3)).from_address(
                ptr.value)).reshape(HEIGHT, WIDTH, 3).copy()
        if self._lib.freenect_sync_get_depth(ctypes.byref(ptr), ctypes.byref(ts), self.index,
                                             DEPTH_MM if mode == "ir" else DEPTH_REGISTERED) < 0:
            raise OSError("no Kinect depth frame")
        depth = np.ctypeslib.as_array((ctypes.c_uint16 * (WIDTH * HEIGHT)).from_address(
            ptr.value)).reshape(HEIGHT, WIDTH).copy()
        return rgb, depth

    def state(self):
        """Accelerometer, tilt angle and motor status, as Motor.state() gives them."""
        ptr = ctypes.POINTER(TiltState)()
        if self._lib.freenect_sync_get_tilt_state(ctypes.byref(ptr), self.index) < 0 or not ptr:
            raise OSError("no tilt state")
        s = ptr.contents
        return {"accel": [s.accelerometer_x, s.accelerometer_y, s.accelerometer_z],
                "tilt": None if s.tilt_angle == -128 else s.tilt_angle / 2.0,
                "status": {0: "stopped", 1: "at-limit", 4: "moving"}.get(s.tilt_status,
                                                                         s.tilt_status)}

    def led(self, colour):
        return self._lib.freenect_sync_set_led(LED[colour], self.index) >= 0

    def tilt(self, degrees):
        return self._lib.freenect_sync_set_tilt_degs(int(max(-27, min(27, degrees))),
                                                     self.index) >= 0

    def close(self):
        self._lib.freenect_sync_stop()
