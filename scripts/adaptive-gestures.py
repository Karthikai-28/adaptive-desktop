#!/usr/bin/env python3
"""Touchpad gestures for the Adaptive session.

GNOME's own touchpad gestures are Wayland-only; on X11 mutter never sees them,
which is why three fingers do nothing here. This reads libinput's own gesture
stream and turns it into window actions, the way libinput-gestures and touchegg
do, without adding a PPA.

    three fingers left / right   previous / next window   (Alt+Tab, but cycling)
    three fingers up             overview
    three fingers down           close the overview

Window switching cycles through _NET_CLIENT_LIST_STACKING rather than tapping
Alt+Tab, because a tapped Alt+Tab only ever toggles between the last two
windows - repeating the gesture would flip back and forth instead of moving on.

Needs read access to the touchpad device:

    sudo apt install -y libinput-tools
    sudo gpasswd -a "$USER" input      # then log out and back in

Test the parser without a touchpad:

    ./scripts/adaptive-gestures.py --replay sample.txt --dry-run
"""

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

LOG_FILE = Path.home() / ".local/state/adaptive-desktop/gestures.log"

# A swipe has to travel before it counts, or resting three fingers twitches
# the window stack.
THRESHOLD = 120.0

# libinput prints:  event10  GESTURE_SWIPE_UPDATE  +1.234s   3  -12.34/  0.56 ...
EVENT = re.compile(
    r"GESTURE_SWIPE_(BEGIN|UPDATE|END)\s+\S+\s+(\d+)(?:\s+([-\d.]+)/\s*([-\d.]+))?"
)


def log(message):
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%F %T')} {message}\n")
    except Exception:
        pass


def sh(*args):
    try:
        return subprocess.run(args, capture_output=True, text=True,
                              timeout=5).stdout.strip()
    except Exception:
        return ""


def windows():
    """Normal windows on the current desktop, in stacking order."""
    raw = sh("xprop", "-root", "_NET_CLIENT_LIST_STACKING")
    ids = re.findall(r"0x[0-9a-fA-F]+", raw)

    current = sh("xprop", "-root", "_NET_CURRENT_DESKTOP")
    desktop = current.rsplit("=", 1)[-1].strip() if "=" in current else ""

    usable = []
    for wid in ids:
        kind = sh("xprop", "-id", wid, "_NET_WM_WINDOW_TYPE")
        if "_NET_WM_WINDOW_TYPE_NORMAL" not in kind:
            continue

        state = sh("xprop", "-id", wid, "_NET_WM_STATE")
        if "_NET_WM_STATE_SKIP_TASKBAR" in state:
            continue

        where = sh("xprop", "-id", wid, "_NET_WM_DESKTOP")
        if desktop and "=" in where:
            if where.rsplit("=", 1)[-1].strip() not in (desktop, "4294967295"):
                continue

        usable.append(wid)

    return usable


def cycle(step, dry_run=False):
    stack = windows()
    if len(stack) < 2:
        log(f"cycle {step}: only {len(stack)} window(s)")
        return

    active = sh("xdotool", "getactivewindow")
    active_hex = f"0x{int(active):08x}" if active.isdigit() else ""

    index = 0
    for i, wid in enumerate(stack):
        if int(wid, 16) == int(active or 0):
            index = i
            break

    target = stack[(index + step) % len(stack)]
    log(f"cycle {step}: {active_hex or active} -> {target}")

    if not dry_run:
        subprocess.run(["xdotool", "windowactivate", str(int(target, 16))],
                       capture_output=True)


def overview(show, dry_run=False):
    log(f"overview {'show' if show else 'hide'}")
    if dry_run:
        return

    # Super toggles the overview; Escape leaves it without toggling anything
    # else on.
    subprocess.run(["xdotool", "key", "super" if show else "Escape"],
                   capture_output=True)


def act(direction, dry_run=False):
    if direction == "right":
        cycle(1, dry_run)
    elif direction == "left":
        cycle(-1, dry_run)
    elif direction == "up":
        overview(True, dry_run)
    elif direction == "down":
        overview(False, dry_run)


def run(stream, fingers_wanted=3, dry_run=False):
    dx = dy = 0.0
    live = False

    for line in stream:
        match = EVENT.search(line)
        if not match:
            continue

        phase, fingers = match.group(1), int(match.group(2))

        if fingers != fingers_wanted:
            live = False
            continue

        if phase == "BEGIN":
            dx = dy = 0.0
            live = True
            continue

        if phase == "UPDATE" and live:
            if match.group(3) is not None:
                dx += float(match.group(3))
                dy += float(match.group(4))
            continue

        if phase == "END" and live:
            live = False

            if max(abs(dx), abs(dy)) < THRESHOLD:
                continue

            if abs(dx) >= abs(dy):
                act("right" if dx > 0 else "left", dry_run)
            else:
                act("down" if dy > 0 else "up", dry_run)


def doctor():
    """Report exactly which prerequisite is missing, and the fix for it."""
    import glob
    import os
    import shutil

    ok = True

    have_libinput = shutil.which("libinput") is not None
    print(f"[{'ok' if have_libinput else 'MISSING'}] libinput-tools")
    if not have_libinput:
        print("        sudo apt install -y libinput-tools")
        ok = False

    in_group = "input" in subprocess.run(
        ["id", "-nG"], capture_output=True, text=True).stdout.split()
    print(f"[{'ok' if in_group else 'MISSING'}] membership of the input group")
    if not in_group:
        print('        sudo gpasswd -a "$USER" input')
        ok = False

    readable = [d for d in glob.glob("/dev/input/event*") if os.access(d, os.R_OK)]
    print(f"[{'ok' if readable else 'MISSING'}] readable event devices "
          f"({len(readable)} of {len(glob.glob('/dev/input/event*'))})")
    if in_group and not readable:
        print("        the group is set but this session predates it - either")
        print("        log out and back in, or start the daemon with:")
        print('        sg input -c "~/adaptive-desktop/scripts/adaptive-gestures.py"')
        ok = False

    touchpad = subprocess.run(["xinput", "list"], capture_output=True,
                              text=True).stdout
    has_pad = "ouchpad" in touchpad
    print(f"[{'ok' if has_pad else 'MISSING'}] touchpad present to X11")

    if ok and have_libinput and readable:
        print()
        print("Prerequisites met. Checking for gesture events for 4 seconds -")
        print("swipe three fingers now.")
        try:
            proc = subprocess.run(["libinput", "debug-events"],
                                  capture_output=True, text=True, timeout=4)
            stream = proc.stdout
        except subprocess.TimeoutExpired as expired:
            stream = expired.stdout or ""
            if isinstance(stream, bytes):
                stream = stream.decode(errors="replace")

        swipes = stream.count("GESTURE_SWIPE")
        print(f"        gesture events seen: {swipes}")
        if not swipes:
            print("        none - this touchpad may not report swipes to")
            print("        libinput. Capture and send the output of:")
            print("        libinput debug-events > /tmp/swipe.txt")

    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doctor", action="store_true",
                    help="check prerequisites and say what is missing")
    ap.add_argument("--fingers", type=int, default=3)
    ap.add_argument("--replay", help="parse a saved debug-events capture")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.doctor:
        return doctor()

    if args.replay:
        with open(args.replay, encoding="utf-8") as handle:
            run(handle, args.fingers, args.dry_run)
        return 0

    try:
        proc = subprocess.Popen(["libinput", "debug-events"],
                                stdout=subprocess.PIPE, text=True, bufsize=1)
    except FileNotFoundError:
        log("libinput not installed - run: sudo apt install -y libinput-tools")
        print("libinput is not installed. Run:\n"
              "  sudo apt install -y libinput-tools\n"
              '  sudo gpasswd -a "$USER" input   # then log out and back in',
              file=sys.stderr)
        return 2

    log(f"gesture daemon started ({args.fingers} fingers)")

    try:
        run(proc.stdout, args.fingers, args.dry_run)
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
