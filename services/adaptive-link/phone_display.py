"""Adaptive Link - the displays made for phones, and what is on them.

virtual_display.py makes one display. This keeps them: one for each phone
that is being used as a display, where its owner put it (left, right, above
or below the computer's own), as large as asked, upright or sideways.

A display outlives the screen that asked for it by a while. The app being
closed, the phone locking, going to another app: none of these should throw
the windows on it back onto the laptop. So the phone lets go of its display
(`release`) rather than taking it away, and it is taken away only if the
phone has not come back for it within GRACE_S. Taken away for whatever
reason, the windows that were on it are remembered, and the next time that
phone becomes a display they are put back where they were - also when it is
made again at another size or the other way up, in proportion.

Every function returns (done, the display's name or why not), as the rest of
machine.py does.
"""

import re
import threading
import time

import machine
import virtual_display

GRACE_S = 120
POSITIONS = {"right": "--right-of", "left": "--left-of", "above": "--above", "below": "--below"}
SIZE = re.compile(r"(\d{3,4})x(\d{3,4})")
NOT_INSTALLED = ("this computer has no display to spare: run scripts/install-link-display.sh on it once, "
                 "then restart the link")


class Made:
    def __init__(self, owner, name, size, position, display):
        self.owner, self.name, self.size, self.position, self.display = owner, name, size, position, display
        self.released = None   # when the phone let go of it, if it has


_made = {}      # owner -> Made
_kept = {}      # owner -> the windows that were on its display, to put back
_lock = threading.RLock()
_listeners = []


def on_change(listener):
    """Call `listener()` whenever a display is made or taken away (the size
    of the whole screen changes with it)."""
    _listeners.append(listener)


def _changed():
    for listener in _listeners:
        try:
            listener()
        except Exception:  # noqa: BLE001 - a listener's trouble is its own
            pass


def made(asker=""):
    """The displays there are: [{name, size, position, mine, leaving}], where
    `leaving` is how many seconds are left of a let-go display's grace."""
    with _lock:
        now = time.monotonic()
        return [{"name": m.name, "size": f"{m.size[0]}x{m.size[1]}", "position": m.position, "mine": m.owner == asker,
                 "leaving": max(0, round(GRACE_S - (now - m.released))) if m.released is not None else None}
                for m in _made.values()]


def display_named(name):
    """The made display by this output name, or None: for sending its frames."""
    with _lock:
        return next((m.display for m in _made.values() if m.name == name), None)


def _size(size):
    match = SIZE.fullmatch(str(size))
    if not match:
        return None
    width, height = int(match.group(1)), int(match.group(2))
    return (width, height) if 320 <= width <= 4096 and 320 <= height <= 4096 else None


# --------------------------------------------------------------- windows

def _geometry(wid):
    """(x, y, width, height) of a window, or None."""
    ok, out = machine._run("xdotool", "getwindowgeometry", "--shell", str(wid), timeout=3)
    found = dict(line.split("=", 1) for line in out.splitlines() if "=" in line) if ok else {}
    try:
        return int(found["X"]), int(found["Y"]), int(found["WIDTH"]), int(found["HEIGHT"])
    except (KeyError, ValueError):
        return None


def _inside(geometry, area):
    x, y, width, height = geometry
    centre_x, centre_y = x + width / 2, y + height / 2
    return area[0] <= centre_x < area[0] + area[2] and area[1] <= centre_y < area[1] + area[3]


def placements(name):
    """The windows on a display, each as where it is in proportion to the
    display: [(id, x, y, width, height, maximized)], fractions of it."""
    area = machine.region(name)
    if not area:
        return []
    found = []
    for window in machine.windows():
        if window["minimized"]:
            continue
        geometry = _geometry(window["id"])
        if geometry and _inside(geometry, area):
            x, y, width, height = geometry
            found.append((window["id"], (x - area[0]) / area[2], (y - area[1]) / area[3],
                          width / area[2], height / area[3], window["maximized"]))
    return found


def _place(wid, area, x, y, width, height, maximize):
    """Put a window on a display: at these fractions of it, or filling it."""
    wid = str(wid)
    current = next((w for w in machine.windows() if str(w["id"]) == wid), None)
    if current is None:
        return False
    if current["maximized"]:
        # A maximized window stays where it is when moved; the desktop's own
        # key lets go of that first.
        machine._run("xdotool", "windowactivate", "--sync", wid, "key", "--clearmodifiers", "super+Down")
    width_px = max(200, min(area[2], round(width * area[2])))
    height_px = max(150, min(area[3], round(height * area[3])))
    left = area[0] + max(0, min(area[2] - width_px, round(x * area[2])))
    top = area[1] + max(0, min(area[3] - height_px, round(y * area[3])))
    machine._run("xdotool", "windowsize", wid, str(width_px), str(height_px))
    done, _ = machine._run("xdotool", "windowmove", wid, str(left), str(top))
    if maximize:
        machine._run("xdotool", "windowactivate", "--sync", wid, "key", "--clearmodifiers", "super+Up")
    return done


def _put_back(kept, name):
    area = None
    for _ in range(12):   # the desktop takes a moment to lay a new display out
        area = machine.region(name)
        if area:
            break
        time.sleep(0.25)
    if not area:
        return 0
    return sum(1 for wid, x, y, width, height, maximized in kept if _place(wid, area, x, y, width, height, maximized))


# ----------------------------------------------------------- making them

def _make(width, height, position):
    """Plug in a monitor of this size and light it beside the others.
    (done, (name, display) or why not)."""
    before = set(machine._outputs_now())
    lit = [output for output in machine.display()["outputs"] if output["on"]]
    display = virtual_display.VirtualDisplay()
    if not display.plug_in(width, height):
        return False, "the display could not be made"
    # The new card's output is the driver's to draw on once it is told so;
    # then it appears as one more connected display.
    name = ""
    for _ in range(20):
        providers = machine._run("xrandr", "--listproviders")[1]
        for line in providers.splitlines():
            found = re.match(r"Provider (\d+):.*name:(\S+)", line)
            if found and "evdi" in found.group(2).lower() or (found and found.group(1) != "0" and "Sink Output" in line):
                machine._run("xrandr", "--setprovideroutputsource", found.group(1), "0")
        new = [output for output in machine._outputs_now() if output not in before]
        if new:
            name = new[0]
            break
        time.sleep(0.25)
    if not name:
        display.unplug()
        return False, "the display was made, but the desktop did not see it"
    main = next((output["name"] for output in lit if output["primary"]), lit[0]["name"] if lit else "")
    # Two phones on the same side go one beyond the other, not on top of it.
    anchor = next((m.name for m in reversed(list(_made.values())) if m.position == position), main)
    done, text = machine._run("xrandr", "--output", name, "--auto", *((POSITIONS[position], anchor) if anchor else ()))
    if not done:
        machine._run("xrandr", "--output", name, "--off")
        display.unplug()
        return False, machine._last_line(text)
    _no_strays({output["name"] for output in lit} | {name}, settle_s=0)
    return True, (name, display)


def _no_strays(was_on, settle_s=2.0):
    """A display coming and going can make the desktop light a port that says
    something is plugged in when nothing is (no EDID, only fallback modes);
    windows sent there would be lost. Any output lit now that was not
    before is put out again - also while the desktop is still rearranging."""
    until = time.monotonic() + settle_s
    while True:
        for output in machine.display()["outputs"]:
            if output["on"] and output["name"] not in was_on:
                machine._run("xrandr", "--output", output["name"], "--off")
        if time.monotonic() >= until:
            return
        time.sleep(0.5)


def _remove(made_one, keep=True):
    """Take a display away; its windows are remembered to be put back."""
    if keep:
        found = placements(made_one.name)
        if found:
            _kept[made_one.owner] = found
    was_on = {output["name"] for output in machine.display()["outputs"] if output["on"]} - {made_one.name}
    machine._run("xrandr", "--output", made_one.name, "--off")
    made_one.display.unplug()
    _made.pop(made_one.owner, None)
    _no_strays(was_on)


def extend(owner, size, position="right"):
    """Make this phone a display of `size` ("WIDTHxHEIGHT"), on the given
    side. A phone that has one already keeps it, or has it made again at the
    new size or place with its windows carried over."""
    wanted = _size(size)
    if wanted is None:
        return False, "a size like 1280x800"
    position = position or "right"
    if position not in POSITIONS:
        return False, "right, left, above or below"
    with _lock:
        current = _made.get(owner)
        if current and current.size == wanted and current.position == position and machine.region(current.name):
            current.released = None
            return True, current.name
        if current is None and not virtual_display.available():
            return False, NOT_INSTALLED
        kept = placements(current.name) if current else _kept.pop(owner, [])
        if current:
            _remove(current, keep=False)
        done, result = _make(*wanted, position)
        if not done:
            if kept:
                _kept[owner] = kept
            _changed()
            return False, result
        name, display = result
        _made[owner] = Made(owner, name, wanted, position, display)
    _changed()
    if kept:
        _put_back(kept, name)
    return True, name


def release(owner):
    """The phone has let go of its display: it is taken away after GRACE_S
    unless the phone comes back for it first."""
    with _lock:
        current = _made.get(owner)
        if current is None:
            return False, "the phone is not a display just now"
        stamp = current.released = time.monotonic()
    timer = threading.Timer(GRACE_S, _expire, (owner, stamp))
    timer.daemon = True
    timer.start()
    return True, current.name


def _expire(owner, stamp):
    with _lock:
        current = _made.get(owner)
        if current is None or current.released != stamp:
            return
        _remove(current)
    _changed()


def unextend(owner, name=""):
    """Take a display away now: this phone's, or the one by this name."""
    with _lock:
        current = _made.get(owner) if owner in _made else next((m for m in _made.values() if m.name == name), None)
        if current is None:
            return False, "the phone is not a display just now"
        _remove(current)
    _changed()
    return True, ""


def unextend_all():
    """Every made display taken away (the link stopping)."""
    with _lock:
        for current in list(_made.values()):
            _remove(current)


def bring(owner, target=""):
    """Put a window - this one, or the one in front - on a phone's display,
    filling it: this phone's, or the one there is."""
    with _lock:
        current = _made.get(owner) or (next(reversed(list(_made.values()))) if _made else None)
    if current is None:
        return False, "no phone is a display just now"
    windows = machine.windows()
    if target:
        window = next((w for w in windows if str(w["id"]) == str(target)), None)
    else:
        window = next((w for w in windows if w["active"]), None)
    if window is None:
        return False, "no such window"
    area = machine.region(current.name)
    if not area or not _place(window["id"], area, 0, 0, 1, 1, True):
        return False, "the window could not be moved"
    return True, current.name
