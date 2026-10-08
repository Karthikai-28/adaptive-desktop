"""Adaptive Link - the phone's touches and keys, turned into pointer and
keyboard input on the laptop.

Events arrive as small JSON objects. translate() turns one into xdotool
commands and is the only way anything reaches xdotool, so it is strict about
what it lets through: numbers are clamped, key names must look like key
names. It has no side effects and is checked directly by verify-link.py.

    {"t": "move", "x": 0.5, "y": 0.5}      absolute, as a fraction of the screen
    {"t": "rel", "dx": 12, "dy": -3}       relative, in pixels (trackpad)
    {"t": "down" | "up" | "click", "b": 1} buttons 1 left, 2 middle, 3 right
    {"t": "double"}                        double click
    {"t": "scroll", "dx": 0, "dy": -2}     wheel steps
    {"t": "key", "k": "Right", "m": ["ctrl"]}
    {"t": "keydown" | "keyup", "k": "w"}   a key held (a game pad's buttons)
    {"t": "text", "s": "hello"}            typed as it is
    {"t": "pen", "x": .5, "y": .5, "p": .7, "s": "down", "e": false, "b": false}
                                           a stylus: pressure, its state (near, down,
                                           move, up, away), eraser end, side button -
                                           drawn through pen.py, not xdotool

X11 only (xdotool). docs/GNOME_PORT.md covers what Wayland would need.
"""

import asyncio
import re
import shutil

_KEY = re.compile(r"^[A-Za-z0-9_]{1,40}$")
MODIFIERS = {"ctrl": "ctrl", "control": "ctrl", "shift": "shift", "alt": "alt",
             "super": "super", "meta": "super"}
MAX_REL = 2000
MAX_SCROLL = 20
MAX_TEXT = 4000


def _number(value, low, high, default=0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return max(low, min(high, number))


def translate(event, screen):
    """[xdotool command, ...] for one event; [] for anything not understood.

    screen is (width, height). A "text" event is not handled here - it is
    typed through a separate xdotool with the text on its stdin, so no text
    is ever part of a command line. See Input.send().
    """
    if not isinstance(event, dict):
        return []
    kind = event.get("t")
    width, height = screen

    if kind == "move":
        x = int(_number(event.get("x"), 0, 1) * max(width - 1, 0))
        y = int(_number(event.get("y"), 0, 1) * max(height - 1, 0))
        return [f"mousemove {x} {y}"]
    if kind == "rel":
        dx = int(_number(event.get("dx"), -MAX_REL, MAX_REL))
        dy = int(_number(event.get("dy"), -MAX_REL, MAX_REL))
        return [f"mousemove_relative -- {dx} {dy}"] if dx or dy else []
    if kind in ("down", "up", "click"):
        button = int(_number(event.get("b", 1), 1, 3, 1))
        return [{"down": "mousedown", "up": "mouseup", "click": "click"}[kind] + f" {button}"]
    if kind == "double":
        return ["click --repeat 2 --delay 80 1"]
    if kind == "scroll":
        commands = []
        dy = int(_number(event.get("dy"), -MAX_SCROLL, MAX_SCROLL))
        dx = int(_number(event.get("dx"), -MAX_SCROLL, MAX_SCROLL))
        if dy:
            commands.append(f"click --repeat {abs(dy)} --delay 0 {5 if dy > 0 else 4}")
        if dx:
            commands.append(f"click --repeat {abs(dx)} --delay 0 {7 if dx > 0 else 6}")
        return commands
    if kind == "key":
        key = event.get("k")
        if not isinstance(key, str) or not _KEY.match(key):
            return []
        modifiers = []
        for name in event.get("m") or []:
            modifier = MODIFIERS.get(str(name).lower())
            if modifier and modifier not in modifiers:
                modifiers.append(modifier)
        return ["key --clearmodifiers " + "+".join(modifiers + [key])]
    if kind in ("keydown", "keyup"):
        key = event.get("k")
        if not isinstance(key, str) or not _KEY.match(key):
            return []
        return [f"{kind} {key}"]
    return []


def held_after(held, event):
    """The keys and buttons held down once this event has been applied, so
    that whatever is still down when the phone goes can be let go of."""
    if not isinstance(event, dict):
        return held
    kind, key = event.get("t"), event.get("k")
    if kind in ("keydown", "keyup") and isinstance(key, str) and _KEY.match(key):
        return held | {f"key {key}"} if kind == "keydown" else held - {f"key {key}"}
    if kind in ("down", "up"):
        button = f"button {int(_number(event.get('b', 1), 1, 3, 1))}"
        return held | {button} if kind == "down" else held - {button}
    return held


def release(held):
    """The events that let go of everything in `held`."""
    return [{"t": "keyup", "k": item.split()[1]} if item.startswith("key ") else {"t": "up", "b": int(item.split()[1])}
            for item in sorted(held)]


def in_region(event, region, screen):
    """A pointer position given as a fraction of one display, as the same
    place on the whole screen. Anything else is passed on as it is."""
    if not region or not isinstance(event, dict) or event.get("t") not in ("move", "pen"):
        return event
    x, y, width, height = region
    whole_w, whole_h = max(screen[0], 1), max(screen[1], 1)
    return dict(event, x=(x + _number(event.get("x"), 0, 1) * width) / whole_w,
                y=(y + _number(event.get("y"), 0, 1) * height) / whole_h)


def pen_as_pointer(event):
    """A pen event as the pointer would take it, where no tablet can be made
    (pen.py): touching is the left button held, lifting lets it go."""
    if not isinstance(event, dict) or event.get("t") != "pen":
        return []
    stage = event.get("s")
    if stage not in ("near", "down", "move", "up"):
        return []
    move = {"t": "move", "x": event.get("x"), "y": event.get("y")}
    return [move] + ([{"t": "down", "b": 1}] if stage == "down" else [{"t": "up", "b": 1}] if stage == "up" else [])


def text_of(event):
    """The text of a "text" event, bounded; "" for anything else."""
    if isinstance(event, dict) and event.get("t") == "text" and isinstance(event.get("s"), str):
        return event["s"][:MAX_TEXT]
    return ""


async def screen_size(env=None):
    """(width, height) of the X screen, or (0, 0) when there is none."""
    if not shutil.which("xdotool"):
        return 0, 0
    proc = await asyncio.create_subprocess_exec(
        "xdotool", "getdisplaygeometry",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env=env)
    out, _ = await proc.communicate()
    try:
        width, height = out.decode().split()
        return int(width), int(height)
    except ValueError:
        return 0, 0


class Input:
    """One long-lived xdotool reading commands, so a pointer move costs a
    line on a pipe rather than a new process."""

    def __init__(self, env=None):
        self.env = env
        self._proc = None
        self.screen = (0, 0)

    async def start(self):
        self.screen = await screen_size(self.env)
        return self.available

    @property
    def available(self):
        return self.screen != (0, 0)

    async def _pipe(self):
        if self._proc is None or self._proc.returncode is not None:
            self._proc = await asyncio.create_subprocess_exec(
                "xdotool", "-", stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, env=self.env)
        return self._proc

    async def send(self, event):
        if not self.available:
            return False
        text = text_of(event)
        if text:
            proc = await asyncio.create_subprocess_exec(
                "xdotool", "type", "--clearmodifiers", "--delay", "0", "--file", "-",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, env=self.env)
            await proc.communicate(text.encode())
            return True
        commands = translate(event, self.screen)
        if not commands:
            return False
        proc = await self._pipe()
        try:
            proc.stdin.write(("\n".join(commands) + "\n").encode())
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            self._proc = None
            return False
        return True

    async def stop(self):
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.stdin.close()
                await asyncio.wait_for(self._proc.wait(), 2)
            except (asyncio.TimeoutError, ProcessLookupError, BrokenPipeError):
                self._proc.kill()
        self._proc = None
