"""Kinect Pad: your body as a gamepad (or arrow keys) for any game on this computer.

The Linux counterpart of FAAST (USC ICT's "skeleton -> keyboard/mouse" toolkit from the
research): a virtual device through uinput that every game, Steam and chiaki-ng (the open-source
PlayStation Remote Play client, so also PS5 games streamed here) sees as an ordinary controller.

Profiles
  wheel   an imaginary steering wheel in both hands (Kinect Joy Ride's idea): left stick X steers,
          right trigger is throttle (hands pushed out), left trigger brake (hands back at the
          chest); jump = A, duck = B, both hands up held = Start
  lean    the same, but steering by leaning your body (no arms held up: easier for children)
  keys    the arrow keys from the same signals, space for jump, for games without a gamepad

When tracking is lost every input is released at once, so a game is never left holding a key.
uinput needs write access to /dev/uinput: scripts/install-kinect-motion.sh --pad adds a udev rule
for the `input` group (asks for sudo once).
"""

import os

DEADZONE = 0.08
EXPO = 1.6            # gentle near the centre, full lock at the ends
STEER_KEY = 0.30      # keys profile: wheel past this presses left/right


def shape(v):
    """Dead zone and exponential response on -1..1 (the research's steering-response advice)."""
    s = 1.0 if v >= 0 else -1.0
    a = abs(v)
    if a < DEADZONE:
        return 0.0
    a = (a - DEADZONE) / (1 - DEADZONE)
    return s * min(1.0, a ** EXPO)


def available():
    """(ok, why): can a virtual device be made here?"""
    import importlib.util
    if importlib.util.find_spec("libevdev") is None:
        return False, "python-libevdev is missing from the Air venv"
    if not os.access("/dev/uinput", os.W_OK):
        return False, "No access to /dev/uinput: run scripts/install-kinect-motion.sh --pad once"
    return True, None


def outputs(profile, wheel, lean, gestures, tracked):
    """What the device should send now: {"axes": {...}, "keys": {...}}. Pure: the checks use it."""
    if not tracked or (wheel is None and profile != "lean"):
        return {"axes": {"steer": 0.0, "throttle": 0.0, "brake": 0.0}, "keys": {}}
    steer = shape(lean if profile == "lean" else wheel["wheel"])
    throttle = wheel["throttle"] if wheel else 0.0
    brake = wheel["brake"] if wheel else 0.0
    names = {g["gesture"] for g in gestures}
    keys = {"jump": "jump" in names, "duck": "duck" in names, "start": "hands_up" in names}
    if profile == "keys":
        keys.update(left=steer < -STEER_KEY, right=steer > STEER_KEY, up=throttle > 0.4, down=brake > 0.5)
    return {"axes": {"steer": round(steer, 3), "throttle": throttle, "brake": brake}, "keys": keys}


class Pad:
    """The uinput device. send(outputs) each frame; close() releases everything."""

    def __init__(self, profile="wheel"):
        import libevdev
        self.ev, self.profile = libevdev, profile
        d = libevdev.Device()
        d.name = "Kinect Pad"
        if profile == "keys":
            self.map = {"left": libevdev.EV_KEY.KEY_LEFT, "right": libevdev.EV_KEY.KEY_RIGHT,
                        "up": libevdev.EV_KEY.KEY_UP, "down": libevdev.EV_KEY.KEY_DOWN,
                        "jump": libevdev.EV_KEY.KEY_SPACE, "duck": libevdev.EV_KEY.KEY_LEFTCTRL,
                        "start": libevdev.EV_KEY.KEY_ENTER}
        else:
            # Shaped like an Xbox pad so games map it without asking.
            d.id = {"bustype": 0x03, "vendor": 0x045E, "product": 0x028E, "version": 1}
            self.map = {"jump": libevdev.EV_KEY.BTN_SOUTH, "duck": libevdev.EV_KEY.BTN_EAST,
                        "start": libevdev.EV_KEY.BTN_START}
            for extra in (libevdev.EV_KEY.BTN_WEST, libevdev.EV_KEY.BTN_NORTH, libevdev.EV_KEY.BTN_SELECT):
                d.enable(extra)
            stick = libevdev.InputAbsInfo(minimum=-32768, maximum=32767, flat=128)
            trig = libevdev.InputAbsInfo(minimum=0, maximum=255)
            for axis, info in ((libevdev.EV_ABS.ABS_X, stick), (libevdev.EV_ABS.ABS_Y, stick),
                               (libevdev.EV_ABS.ABS_RX, stick), (libevdev.EV_ABS.ABS_RY, stick),
                               (libevdev.EV_ABS.ABS_Z, trig), (libevdev.EV_ABS.ABS_RZ, trig)):
                d.enable(axis, info)
        for code in self.map.values():
            d.enable(code)
        self.dev = d.create_uinput_device()
        self.down = set()
        self.last = None

    def send(self, out):
        ev, events = self.ev, []
        for name, code in self.map.items():
            want = bool(out["keys"].get(name))
            if want != (name in self.down):
                events.append(ev.InputEvent(code, 1 if want else 0))
                (self.down.add if want else self.down.discard)(name)
        if self.profile != "keys":
            a = out["axes"]
            vals = (int(a["steer"] * 32767), int(a["throttle"] * 255), int(a["brake"] * 255))
            if vals != self.last:
                events += [ev.InputEvent(ev.EV_ABS.ABS_X, vals[0]), ev.InputEvent(ev.EV_ABS.ABS_RZ, vals[1]),
                           ev.InputEvent(ev.EV_ABS.ABS_Z, vals[2])]
                self.last = vals
        if events:
            self.dev.send_events(events + [ev.InputEvent(ev.EV_SYN.SYN_REPORT, 0)])

    def close(self):
        try:
            self.send({"axes": {"steer": 0.0, "throttle": 0.0, "brake": 0.0}, "keys": {}})
        finally:
            self.dev = None
