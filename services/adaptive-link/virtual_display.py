"""Adaptive Link - a display that exists only for the phone.

Extending the desktop onto the phone needs a display for the desktop to
extend onto. X and the window manager only extend onto outputs the graphics
driver has, and a driver will not light an output with nothing plugged into
it. So the output is made: evdi is a kernel module (the one DisplayLink docks
use) that adds a graphics device whose "monitor" is whatever a program says
it is. This is that program. It tells the device a monitor of the phone's
size has been plugged in, and holds it there; the desktop then sees one more
display and extends onto it like any other, and the link sends that part of
the screen to the phone.

The module needs root to install (scripts/install-link-display.sh), once.
Without it `available()` is false and the phone is told what to run.

`edid` - the description of the monitor, 128 bytes in the form every monitor
gives - is made here from the size asked for, and is checked by
verify-link.py with no device at all.
"""

import ctypes
import ctypes.util
import re
import select
import subprocess
import threading
import time
from pathlib import Path

LIBRARIES = ("libevdi.so.1", "libevdi.so.0", "libevdi.so")
SYS = Path("/sys/devices/evdi")
AVAILABLE = 0   # evdi_check_device: this card is an evdi device, free to use


def modeline(width, height, rate=60):
    """The timings for a display of this size, as `cvt` works them out:
    {clock (MHz), h: [active, sync start, sync end, total], v: [...]}."""
    try:
        out = subprocess.run(["cvt", str(width), str(height), str(rate)], capture_output=True, text=True,
                             timeout=3, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r'^Modeline\s+"[^"]*"\s+([\d.]+)\s+(\d+) (\d+) (\d+) (\d+)\s+(\d+) (\d+) (\d+) (\d+)', out, re.MULTILINE)
    if not match:
        return None
    numbers = [int(value) for value in match.groups()[1:]]
    return {"clock": float(match.group(1)), "h": numbers[:4], "v": numbers[4:]}


def edid(width, height, timings, name="Phone"):
    """A monitor's description of itself (EDID 1.3): one that is `width` by
    `height` and nothing else."""
    h_active, h_start, h_end, h_total = timings["h"]
    v_active, v_start, v_end, v_total = timings["v"]
    h_blank, v_blank = h_total - h_active, v_total - v_active
    h_offset, h_pulse = h_start - h_active, h_end - h_start
    v_offset, v_pulse = v_start - v_active, v_end - v_start
    clock = int(round(timings["clock"] * 100))   # in units of 10 kHz
    # About the size of a phone held sideways, in millimetres; only its shape matters.
    mm_w, mm_h = 150, max(1, round(150 * height / width))

    block = bytearray(128)
    block[0:8] = bytes([0, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0])
    # Who made it, as three letters packed into two bytes: "ADP".
    letters = [ord(letter) - ord("A") + 1 for letter in "ADP"]
    maker = (letters[0] << 10) | (letters[1] << 5) | letters[2]
    block[8:10] = bytes([maker >> 8, maker & 0xFF])
    block[10:12] = bytes([0x01, 0x00])           # product
    block[12:16] = bytes([1, 0, 0, 0])           # serial
    block[16:18] = bytes([1, 35])                # week, year (1990 + 35)
    block[18:20] = bytes([1, 3])                 # EDID 1.3
    block[20] = 0x80                             # a digital input
    block[21:23] = bytes([mm_w // 10, mm_h // 10])
    block[23] = 120                              # gamma 2.2
    block[24] = 0x0A                             # RGB, and the first timing below is the one to use
    block[38:54] = bytes([1, 1] * 8)             # no standard timings

    detail = bytearray(18)
    detail[0:2] = bytes([clock & 0xFF, clock >> 8])
    detail[2] = h_active & 0xFF
    detail[3] = h_blank & 0xFF
    detail[4] = ((h_active >> 8) << 4) | (h_blank >> 8)
    detail[5] = v_active & 0xFF
    detail[6] = v_blank & 0xFF
    detail[7] = ((v_active >> 8) << 4) | (v_blank >> 8)
    detail[8] = h_offset & 0xFF
    detail[9] = h_pulse & 0xFF
    detail[10] = ((v_offset & 0x0F) << 4) | (v_pulse & 0x0F)
    detail[11] = ((h_offset >> 8) << 6) | ((h_pulse >> 8) << 4) | ((v_offset >> 4) << 2) | (v_pulse >> 4)
    detail[12] = mm_w & 0xFF
    detail[13] = mm_h & 0xFF
    detail[14] = ((mm_w >> 8) << 4) | (mm_h >> 8)
    detail[17] = 0x1A                            # digital, separate sync, +vsync
    block[54:72] = detail

    def text(tag, value):
        body = value.encode("ascii", "replace")[:13]
        return bytes([0, 0, 0, tag, 0]) + body + (b"\n" if len(body) < 13 else b"") + b" " * max(0, 12 - len(body))

    block[72:90] = text(0xFC, name)              # its name
    block[90:108] = bytes([0, 0, 0, 0xFD, 0, 50, 75, 30, 160, max(1, clock // 1000 + 1), 0, 0x0A]) + b" " * 6   # what it can sync to
    block[108:126] = text(0xFE, "Adaptive Link")
    block[127] = (256 - sum(block[:127])) % 256
    return bytes(block)


def read_edid(block):
    """(width, height) the description says, or None if it is not one:
    what a graphics driver would make of it."""
    if len(block) != 128 or block[0:8] != bytes([0, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0]) or sum(block) % 256:
        return None
    detail = block[54:72]
    return detail[2] | ((detail[4] >> 4) << 8), detail[5] | ((detail[7] >> 4) << 8)


def _library():
    for name in LIBRARIES:
        try:
            return ctypes.CDLL(name)
        except OSError:
            continue
    return None


_in_use = set()   # the cards a display made here holds; evdi says only whether a card is evdi's


def _cards():
    """Every evdi graphics card there is."""
    library = _library()
    if library is None:
        return []
    found = []
    for card in sorted(Path("/dev/dri").glob("card*")):
        number = int(card.name[4:])
        if library.evdi_check_device(number) == AVAILABLE:
            found.append(number)
    return found


def _device():
    """The number of an evdi graphics card that is free to use, or -1."""
    return next((number for number in _cards() if number not in _in_use), -1)


def available():
    """Whether a display can be made here: the module is loaded with a device
    to spare, and its library is installed."""
    return SYS.exists() and _device() >= 0


def capacity():
    """How many displays can be made here at once (one for each evdi card)."""
    return len(_cards()) if SYS.exists() else 0


class _Rect(ctypes.Structure):
    _fields_ = [("x1", ctypes.c_int), ("y1", ctypes.c_int), ("x2", ctypes.c_int), ("y2", ctypes.c_int)]


class _Mode(ctypes.Structure):
    _fields_ = [("width", ctypes.c_int), ("height", ctypes.c_int), ("refresh_rate", ctypes.c_int),
                ("bits_per_pixel", ctypes.c_int), ("pixel_format", ctypes.c_uint)]


class _Buffer(ctypes.Structure):
    _fields_ = [("id", ctypes.c_int), ("buffer", ctypes.c_void_p), ("width", ctypes.c_int), ("height", ctypes.c_int),
                ("stride", ctypes.c_int), ("rects", ctypes.POINTER(_Rect)), ("rect_count", ctypes.c_int)]


_ON_MODE = ctypes.CFUNCTYPE(None, _Mode, ctypes.c_void_p)
_ON_UPDATE = ctypes.CFUNCTYPE(None, ctypes.c_int, ctypes.c_void_p)


class _Events(ctypes.Structure):
    # Only the two handlers this needs; libevdi skips the ones left empty.
    _fields_ = [("dpms", ctypes.c_void_p), ("mode_changed", _ON_MODE), ("update_ready", _ON_UPDATE),
                ("crtc_state", ctypes.c_void_p), ("cursor_set", ctypes.c_void_p), ("cursor_move", ctypes.c_void_p),
                ("ddcci_data", ctypes.c_void_p), ("user_data", ctypes.c_void_p)]


MAX_DIRTS = 16     # the most changed areas libevdi reports in one grab
FRAME = 1 / 60     # how often the display is asked for what changed


class VirtualDisplay:
    """One display made for the phone, there for as long as this is held.

    Plugging the monitor in is not enough. While it is connected the device
    holds back the desktop's next frame until someone has taken the last
    one, so with nobody taking them the desktop stops at its first frame
    (setting the display's mode hangs X). So a thread here does what a
    DisplayLink dock's own program does: it gives the device a buffer the
    size of the mode the desktop chose and keeps taking frames into it.

    Those frames are the picture the phone is sent (`frame()`): what the
    desktop drew, the pointer drawn in by the device, taken only when
    something on the display changed - not a second capture of the screen.
    """

    def __init__(self):
        self._library = None
        self._handle = None
        self._edid = None
        self._thread = None
        self._stop = threading.Event()
        self._buffer = None     # (the memory, its id) once the desktop has chosen a mode
        self._waiting = False   # asked for a frame, and told it will come with an event
        self._rects = (_Rect * MAX_DIRTS)()
        self._events = _Events(mode_changed=_ON_MODE(self._on_mode), update_ready=_ON_UPDATE(self._on_update))
        self._card = -1
        self._lock = threading.Lock()
        self._fresh = threading.Condition(self._lock)
        self._mode = None     # (width, height, stride) of the frames being taken
        self._changed = 0     # counts the grabs that found something changed

    def plug_in(self, width, height):
        """Tell the desktop a monitor of this size has been connected.
        Returns whether it was."""
        timings = modeline(width, height)
        library, device = _library(), _device()
        if timings is None or library is None or device < 0:
            return False
        library.evdi_open.restype = ctypes.c_void_p
        # 1.10 and later take a fifth limit (pixels a second, 0 for none); an
        # earlier library ignores the extra argument.
        library.evdi_connect.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint32, ctypes.c_uint32]
        library.evdi_disconnect.argtypes = [ctypes.c_void_p]
        library.evdi_close.argtypes = [ctypes.c_void_p]
        library.evdi_get_event_ready.argtypes = [ctypes.c_void_p]
        library.evdi_get_event_ready.restype = ctypes.c_int
        library.evdi_handle_events.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Events)]
        library.evdi_register_buffer.argtypes = [ctypes.c_void_p, _Buffer]
        library.evdi_unregister_buffer.argtypes = [ctypes.c_void_p, ctypes.c_int]
        library.evdi_request_update.argtypes = [ctypes.c_void_p, ctypes.c_int]
        library.evdi_request_update.restype = ctypes.c_bool
        library.evdi_grab_pixels.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Rect), ctypes.POINTER(ctypes.c_int)]
        handle = library.evdi_open(device)
        if not handle:
            return False
        self._card = device
        _in_use.add(device)
        # Kept, because the device reads it for as long as the monitor is there.
        self._edid = ctypes.create_string_buffer(edid(width, height, timings), 128)
        library.evdi_connect(handle, self._edid, 128, width * height, 0)
        self._library, self._handle = library, handle
        self._stop.clear()
        self._thread = threading.Thread(target=self._serve, name="phone-display", daemon=True)
        self._thread.start()
        return True

    def unplug(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._thread = None
        if self._handle:
            self._library.evdi_disconnect(self._handle)
            self._library.evdi_close(self._handle)
        _in_use.discard(self._card)
        self._card = -1
        self._handle = None
        self._edid = None
        with self._lock:
            self._buffer = None
            self._mode = None
            self._fresh.notify_all()

    def _serve(self):
        """Take each frame the desktop draws on this display, so it draws the next."""
        library, handle = self._library, self._handle
        ready = library.evdi_get_event_ready(handle)
        asked = 0.0
        while not self._stop.is_set():
            if self._buffer is not None and not self._waiting and time.monotonic() - asked >= FRAME:
                asked = time.monotonic()
                if library.evdi_request_update(handle, self._buffer[1]):
                    self._grab()
                else:
                    self._waiting = True
            try:
                events, _, _ = select.select([ready], [], [], FRAME)
            except (OSError, ValueError):
                break
            if events:
                library.evdi_handle_events(handle, ctypes.byref(self._events))

    def _on_mode(self, mode, _user):
        """The desktop chose a mode: a buffer the size of it to take frames into."""
        library, handle = self._library, self._handle
        with self._lock:
            if self._buffer is not None:
                library.evdi_unregister_buffer(handle, self._buffer[1])
            stride = mode.width * 4
            memory = ctypes.create_string_buffer(stride * mode.height)
            number = 1 if self._buffer is None else self._buffer[1] + 1
            library.evdi_register_buffer(handle, _Buffer(number, ctypes.cast(memory, ctypes.c_void_p), mode.width,
                                                         mode.height, stride, self._rects, MAX_DIRTS))
            self._buffer = (memory, number)
            self._mode = (mode.width, mode.height, stride)
            self._changed += 1
            self._waiting = False

    def _on_update(self, _buffer, _user):
        self._grab()

    def _grab(self):
        count = ctypes.c_int(MAX_DIRTS)
        with self._lock:
            self._library.evdi_grab_pixels(self._handle, self._rects, ctypes.byref(count))
            self._waiting = False
            if count.value > 0:
                self._changed += 1
                self._fresh.notify_all()

    def frame(self, after=-1, timeout=1.0):
        """(number, pixels, width, height) of the display's picture once it is
        newer than frame `after`, or None if nothing changed within `timeout`.
        The pixels are 4 bytes each, blue green red and one unused, row after
        row with nothing between."""
        with self._fresh:
            if self._changed == after or self._mode is None:
                self._fresh.wait(timeout)
            if self._mode is None or self._buffer is None or self._changed == after:
                return None
            width, height, stride = self._mode
            return self._changed, ctypes.string_at(self._buffer[0], stride * height), width, height

    @property
    def plugged(self):
        return self._handle is not None
