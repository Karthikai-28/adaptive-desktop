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
import subprocess
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


def _device():
    """The number of an evdi graphics card that is free to use, or -1."""
    library = _library()
    if library is None:
        return -1
    for card in sorted(Path("/dev/dri").glob("card*")):
        number = int(card.name[4:])
        if library.evdi_check_device(number) == AVAILABLE:
            return number
    return -1


def available():
    """Whether a display can be made here: the module is loaded with a device
    to spare, and its library is installed."""
    return SYS.exists() and _device() >= 0


class VirtualDisplay:
    """One display made for the phone, there for as long as this is held."""

    def __init__(self):
        self._library = None
        self._handle = None
        self._edid = None

    def plug_in(self, width, height):
        """Tell the desktop a monitor of this size has been connected.
        Returns whether it was."""
        timings = modeline(width, height)
        library, device = _library(), _device()
        if timings is None or library is None or device < 0:
            return False
        library.evdi_open.restype = ctypes.c_void_p
        library.evdi_connect.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint32]
        library.evdi_disconnect.argtypes = [ctypes.c_void_p]
        library.evdi_close.argtypes = [ctypes.c_void_p]
        handle = library.evdi_open(device)
        if not handle:
            return False
        # Kept, because the device reads it for as long as the monitor is there.
        self._edid = ctypes.create_string_buffer(edid(width, height, timings), 128)
        library.evdi_connect(handle, self._edid, 128, ctypes.c_uint32(width * height))
        self._library, self._handle = library, handle
        return True

    def unplug(self):
        if self._handle:
            self._library.evdi_disconnect(self._handle)
            self._library.evdi_close(self._handle)
        self._handle = None
        self._edid = None

    @property
    def plugged(self):
        return self._handle is not None
