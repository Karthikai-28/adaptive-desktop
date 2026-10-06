"""Adaptive Link - the phone's stylus as a drawing tablet on the computer.

A finger on the phone moves the pointer and clicks (inputs.py, through
xdotool). A stylus can say more: how hard it presses, whether it is near
the glass without touching, its eraser end, its button. xdotool can say
none of that, so a pen gets a device of its own: a tablet made through the
kernel's uinput, which the desktop and drawing programs (Krita, GIMP,
Xournal++) treat as any graphics tablet - pressure for line width, the
eraser as an eraser.

The tablet covers the whole screen, as a tablet does by default; where on
it the pen is was worked out from the display the phone shows
(inputs.in_region), so the pen lands where it is on the phone's picture.

/dev/uinput belongs to root until scripts/install-link-pen.sh hands it to
whoever is at the computer's seat, once. Until then `available()` is false and pen strokes
fall back to the pointer: touched is a click held, lifted is let go.
"""

import fcntl
import os
import struct
import threading
import time

UINPUT = "/dev/uinput"
NAME = b"Adaptive Link pen"
RANGE = 32767           # the tablet's coordinates, either way
PRESSURE = 4095

# linux/input-event-codes.h
EV_SYN, EV_KEY, EV_ABS = 0x00, 0x01, 0x03
SYN_REPORT = 0
ABS_X, ABS_Y, ABS_PRESSURE = 0x00, 0x01, 0x18
BTN_TOOL_PEN, BTN_TOOL_RUBBER, BTN_TOUCH, BTN_STYLUS = 0x140, 0x141, 0x14a, 0x14b
INPUT_PROP_DIRECT = 0x01   # drawn on where it is shown, as a pen display
BUS_VIRTUAL = 0x06


def _ioc(direction, number, size):
    return (direction << 30) | (size << 16) | (ord("U") << 8) | number


UI_DEV_CREATE = _ioc(0, 1, 0)
UI_DEV_DESTROY = _ioc(0, 2, 0)
UI_DEV_SETUP = _ioc(1, 3, 92)          # struct uinput_setup
UI_ABS_SETUP = _ioc(1, 4, 28)          # struct uinput_abs_setup
UI_SET_EVBIT = _ioc(1, 100, 4)
UI_SET_KEYBIT = _ioc(1, 101, 4)
UI_SET_ABSBIT = _ioc(1, 103, 4)
UI_SET_PROPBIT = _ioc(1, 110, 4)


def available():
    """Whether a tablet can be made here: /dev/uinput is open to this user."""
    return os.access(UINPUT, os.W_OK)


def _number(value, low, high):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return low
    return low if number != number else max(low, min(high, number))


def reports(event, screen, state):
    """The input events (type, code, value) for one pen event, and the pen's
    state after it ({"near", "down", "rubber", "button"}). No side effects:
    checked directly by verify-link.py.

    event: {"t": "pen", "x", "y" (fractions of the whole screen), "p"
    (pressure 0..1), "s": "near" | "down" | "move" | "up" | "away",
    "e": eraser end, "b": side button}
    """
    if not isinstance(event, dict) or event.get("t") != "pen":
        return [], state
    stage = event.get("s")
    if stage not in ("near", "down", "move", "up", "away"):
        return [], state
    state = dict(state)
    out = []
    rubber = bool(event.get("e"))
    tool = BTN_TOOL_RUBBER if rubber else BTN_TOOL_PEN
    if state.get("near") and state.get("rubber") != rubber:
        # The pen turned over: the other end leaves before this one arrives.
        out.append((EV_KEY, BTN_TOOL_RUBBER if state["rubber"] else BTN_TOOL_PEN, 0))
        state["near"] = False
    if stage == "away":
        if state.get("down"):
            out += [(EV_ABS, ABS_PRESSURE, 0), (EV_KEY, BTN_TOUCH, 0)]
        if state.get("near"):
            out.append((EV_KEY, tool, 0))
        out.append((EV_SYN, SYN_REPORT, 0))
        return out, {"near": False, "down": False, "rubber": rubber, "button": False}
    if not state.get("near"):
        out.append((EV_KEY, tool, 1))
        state["near"], state["rubber"] = True, rubber
    out += [(EV_ABS, ABS_X, round(_number(event.get("x"), 0, 1) * RANGE)),
            (EV_ABS, ABS_Y, round(_number(event.get("y"), 0, 1) * RANGE))]
    touching = stage in ("down", "move") and (stage == "down" or state.get("down"))
    out.append((EV_ABS, ABS_PRESSURE, round(_number(event.get("p"), 0, 1) * PRESSURE) if touching else 0))
    if touching != bool(state.get("down")):
        out.append((EV_KEY, BTN_TOUCH, 1 if touching else 0))
        state["down"] = touching
    button = bool(event.get("b"))
    if button != bool(state.get("button")):
        out.append((EV_KEY, BTN_STYLUS, 1 if button else 0))
        state["button"] = button
    out.append((EV_SYN, SYN_REPORT, 0))
    return out, state


class Pen:
    """The tablet, made the first time a pen is used and kept."""

    def __init__(self):
        self._fd = None
        self._state = {}
        self._lock = threading.Lock()

    def _open(self):
        fd = os.open(UINPUT, os.O_WRONLY | os.O_NONBLOCK)
        try:
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_ABS)
            for key in (BTN_TOOL_PEN, BTN_TOOL_RUBBER, BTN_TOUCH, BTN_STYLUS):
                fcntl.ioctl(fd, UI_SET_KEYBIT, key)
            fcntl.ioctl(fd, UI_SET_PROPBIT, INPUT_PROP_DIRECT)
            for axis, top, resolution in ((ABS_X, RANGE, 100), (ABS_Y, RANGE, 100), (ABS_PRESSURE, PRESSURE, 0)):
                fcntl.ioctl(fd, UI_SET_ABSBIT, axis)
                # struct uinput_abs_setup: code, then input_absinfo (value,
                # minimum, maximum, fuzz, flat, resolution). A resolution
                # is what tells the desktop it is a tablet and not a joystick.
                fcntl.ioctl(fd, UI_ABS_SETUP, struct.pack("<H2x6i", axis, 0, 0, top, 0, 0, resolution))
            fcntl.ioctl(fd, UI_DEV_SETUP, struct.pack("<4H80sI", BUS_VIRTUAL, 0x1209, 0xad11, 1, NAME, 0))
            fcntl.ioctl(fd, UI_DEV_CREATE)
        except OSError:
            os.close(fd)
            raise
        return fd

    def send(self, event, screen=None):
        """Draw one pen event. Returns whether it reached a tablet."""
        with self._lock:
            if self._fd is None:
                if not available():
                    return False
                try:
                    self._fd = self._open()
                except OSError:
                    return False
                time.sleep(0.2)   # the desktop picks up a new device in a moment
            found, self._state = reports(event, screen, self._state)
            if not found:
                return False
            seconds = time.time()
            stamp = (int(seconds), int(seconds % 1 * 1_000_000))
            try:
                os.write(self._fd, b"".join(struct.pack("<qqHHi", *stamp, kind, code, value)
                                            for kind, code, value in found))
            except OSError:
                return False
            return True

    def close(self):
        with self._lock:
            if self._fd is not None:
                try:
                    fcntl.ioctl(self._fd, UI_DEV_DESTROY)
                except OSError:
                    pass
                os.close(self._fd)
                self._fd = None
