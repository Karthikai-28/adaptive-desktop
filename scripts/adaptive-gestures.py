#!/usr/bin/env python3
"""Touchpad gestures for the Adaptive session, set up the way Windows does.

GNOME's own touchpad gestures are Wayland-only; on X11 mutter never sees them.
This reads libinput's gesture stream and turns three- and four-finger swipes
(and a four-finger tap) into actions chosen in the Touchpad Gestures app
(apps/adaptive-gestures), saved to ~/.config/adaptive-desktop/gestures.json.

Each finger count takes a Windows preset or a custom action per direction:

    Switch apps and show desktop      up: task view   down: desktop
                                      left / right: previous / next app
    Switch desktops and show desktop  up: task view   down: desktop
                                      left / right: previous / next workspace
    Change audio and volume           up / down: volume
                                      left / right: previous / next track

Defaults match Windows: three fingers switch apps, four switch desktops.

Actions only the shell can perform (app grid, search, the notification and
control centres, animated workspace switching) go through the Adaptive Shell's
own D-Bus method; see shell/adaptive-shell@local/shellActions.js. The rest are
window operations and media keys from here.

The settings file is re-read whenever it changes, so edits in the app apply to
the next swipe with no restart. The last recognised gesture is written to
~/.local/state/adaptive-desktop/gesture-last.json for the app's "Try it" row.

Needs read access to the touchpad device (the input group). Check with:

    ./scripts/adaptive-gestures.py --doctor

Test the parser without a touchpad:

    ./scripts/adaptive-gestures.py --replay sample.txt --dry-run
"""

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

STATE_DIR = Path.home() / ".local/state/adaptive-desktop"
LOG_FILE = STATE_DIR / "gestures.log"
LAST_FILE = STATE_DIR / "gesture-last.json"
CONFIG_FILE = Path.home() / ".config/adaptive-desktop/gestures.json"

DIRECTIONS = ("up", "down", "left", "right")

# Presets, named as Windows names them.
PRESETS = {
    "switch-apps": {
        "label": "Switch apps and show desktop",
        "up": "overview", "down": "show-desktop",
        "left": "previous-app", "right": "next-app",
    },
    "switch-desktops": {
        "label": "Switch desktops and show desktop",
        "up": "overview", "down": "show-desktop",
        "left": "workspace-left", "right": "workspace-right",
    },
    "audio": {
        "label": "Change audio and volume",
        "up": "volume-up", "down": "volume-down",
        "left": "previous-track", "right": "next-track",
    },
    "nothing": {
        "label": "Nothing",
        "up": "none", "down": "none", "left": "none", "right": "none",
    },
}

# Every action a direction or tap can take. The settings app reads this list
# (python3 adaptive-gestures.py --list-actions) so the two never disagree.
ACTIONS = {
    "none": "Nothing",
    "overview": "Task view (Activities)",
    "app-grid": "Show all apps",
    "search": "Search",
    "show-desktop": "Show desktop (minimise all)",
    "next-app": "Next app",
    "previous-app": "Previous app",
    "workspace-right": "Next desktop",
    "workspace-left": "Previous desktop",
    "window-to-workspace-right": "Move window to next desktop",
    "window-to-workspace-left": "Move window to previous desktop",
    "notifications": "Notification center",
    "control-center": "Control center",
    "maximize": "Maximize window",
    "minimize": "Minimize window",
    "snap-left": "Snap window left",
    "snap-right": "Snap window right",
    "volume-up": "Volume up",
    "volume-down": "Volume down",
    "mute": "Mute",
    "play-pause": "Play / pause",
    "next-track": "Next track",
    "previous-track": "Previous track",
    "back": "Back (browser, Files)",
    "forward": "Forward (browser, Files)",
    "screenshot": "Screenshot",
    "next-wallpaper": "Next wallpaper",
    "custom": "Custom shortcut",
}

DEFAULTS = {
    "enabled": True,
    "sensitivity": "medium",
    "3": {"preset": "switch-apps", "custom": {}, "shortcut": {}},
    "4": {"preset": "switch-desktops", "custom": {}, "shortcut": {}, "tap": "notifications"},
    # Press and release Ctrl twice, on its own, to minimise every window
    # (again, on an empty desktop, to bring them back).
    # Press and release Alt twice, on its own, to change the wallpaper.
    "keyboard": {"double_ctrl": "show-desktop", "double_alt": "next-wallpaper"},
}

# Distance a swipe must travel, in libinput's unaccelerated units.
SENSITIVITY = {"low": 180.0, "medium": 120.0, "high": 70.0}

# A four-finger touch that lifts within this long, without swiping, is a tap.
TAP_SECONDS = 0.35

# Double Ctrl / Alt: a press and release of the key alone counts as a tap when
# short; a second tap soon after the first is the double press.
CTRL_TAP_SECONDS = 0.30
CTRL_GAP_SECONDS = 0.40

# libinput hides key names unless --show-keycodes is given, and a double Ctrl
# cannot be told apart without it. Each keyboard line is only checked against
# Ctrl and then dropped: no key is stored, logged or written anywhere.
KEY = re.compile(r"KEYBOARD_KEY\s+\+?([\d.]+)s\s+(\S+) \((-?\d+)\) (pressed|released)")
POINTER_BUTTON = re.compile(r"POINTER_(BUTTON|SCROLL|AXIS)")
CTRL_KEYS = {"KEY_LEFTCTRL", "KEY_RIGHTCTRL"}
ALT_KEYS = {"KEY_LEFTALT", "KEY_RIGHTALT"}

WALLPAPER_SCRIPT = Path(__file__).resolve().parent / "adaptive-wallpaper.sh"

# libinput prints:  event10  GESTURE_SWIPE_UPDATE  +1.234s   3  -12.34/  0.56 ...
EVENT = re.compile(
    r"GESTURE_(SWIPE|HOLD)_(BEGIN|UPDATE|END)\s+\+?([\d.]+)s\s+(\d+)"
    r"(?:\s+([-\d.]+)/\s*([-\d.]+))?(\s+cancelled)?"
)


def log(message):
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
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


# ------------------------------------------------------------------
# Settings
# ------------------------------------------------------------------


class Settings:
    """gestures.json, re-read whenever its modification time changes."""

    def __init__(self, path=CONFIG_FILE):
        self.path = path
        self.stamp = None
        self.data = json.loads(json.dumps(DEFAULTS))

    def current(self):
        try:
            stamp = self.path.stat().st_mtime_ns
        except FileNotFoundError:
            stamp = None
        if stamp != self.stamp:
            self.stamp = stamp
            merged = json.loads(json.dumps(DEFAULTS))
            if stamp is not None:
                try:
                    loaded = json.loads(self.path.read_text(encoding="utf-8"))
                    for key, value in loaded.items():
                        if isinstance(value, dict) and isinstance(merged.get(key), dict):
                            merged[key].update(value)
                        else:
                            merged[key] = value
                    log("settings loaded")
                except (OSError, ValueError) as error:
                    log(f"settings unreadable, using defaults: {error}")
            self.data = merged
        return self.data

    def action_for(self, fingers, direction):
        data = self.current()
        group = data.get(str(fingers)) or {}
        preset = group.get("preset", "nothing")
        if preset == "custom":
            return group.get("custom", {}).get(direction, "none"), group
        return PRESETS.get(preset, PRESETS["nothing"]).get(direction, "none"), group

    def threshold(self):
        return SENSITIVITY.get(self.current().get("sensitivity"), SENSITIVITY["medium"])


# ------------------------------------------------------------------
# Window helpers (X11)
# ------------------------------------------------------------------


def windows():
    """Normal windows on the current desktop, in the order they were opened.

    Left and right walk _NET_CLIENT_LIST, creation order, not stacking order:
    stacking is most-recently-used and reshuffles on every switch, so "right"
    would stop meaning the same neighbour after one gesture.
    """
    raw = sh("xprop", "-root", "_NET_CLIENT_LIST")
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


def cycle(step):
    stack = windows()
    if len(stack) < 2:
        log(f"cycle {step}: only {len(stack)} window(s)")
        return
    active = sh("xdotool", "getactivewindow")
    index = 0
    for i, wid in enumerate(stack):
        if active.isdigit() and int(wid, 16) == int(active):
            index = i
            break
    target = stack[(index + step) % len(stack)]
    subprocess.run(["xdotool", "windowactivate", str(int(target, 16))],
                   capture_output=True)


def show_desktop():
    """Minimise everything, or restore it if the desktop is already bare, so a
    second swipe down undoes the first."""
    stack = windows()
    if not stack:
        return
    hidden = [wid for wid in stack
              if "_NET_WM_STATE_HIDDEN" in sh("xprop", "-id", wid, "_NET_WM_STATE")]
    restoring = len(hidden) == len(stack)
    for wid in stack:
        action = "windowactivate" if restoring else "windowminimize"
        subprocess.run(["xdotool", action, str(int(wid, 16))], capture_output=True)


def shell(action):
    """An action only the shell can do, through the Adaptive Shell's method."""
    result = subprocess.run(
        ["gdbus", "call", "--session", "-d", "org.gnome.Shell",
         "-o", "/org/adaptive/Shell", "-m", "org.adaptive.Shell.Run", action],
        capture_output=True, text=True, timeout=5)
    if "true" not in result.stdout:
        log(f"shell action {action} not handled: {result.stderr.strip() or result.stdout.strip()}")


def keys(*combo):
    subprocess.run(["xdotool", "key", "--clearmodifiers", *combo], capture_output=True)


# Media and volume go through the media keys, so GNOME shows its own OSD and
# routes play/pause to whichever player is active, as a keyboard would.
HANDLERS = {
    "overview": lambda: shell("overview"),
    "app-grid": lambda: shell("app-grid"),
    "search": lambda: shell("search"),
    "notifications": lambda: shell("notifications"),
    "control-center": lambda: shell("control-center"),
    "workspace-left": lambda: shell("workspace-left"),
    "workspace-right": lambda: shell("workspace-right"),
    "window-to-workspace-left": lambda: shell("window-to-workspace-left"),
    "window-to-workspace-right": lambda: shell("window-to-workspace-right"),
    "show-desktop": show_desktop,
    "next-app": lambda: cycle(1),
    "previous-app": lambda: cycle(-1),
    "maximize": lambda: keys("super+Up"),
    "minimize": lambda: keys("super+h"),
    "snap-left": lambda: keys("super+Left"),
    "snap-right": lambda: keys("super+Right"),
    "volume-up": lambda: keys("XF86AudioRaiseVolume"),
    "volume-down": lambda: keys("XF86AudioLowerVolume"),
    "mute": lambda: keys("XF86AudioMute"),
    "play-pause": lambda: keys("XF86AudioPlay"),
    "next-track": lambda: keys("XF86AudioNext"),
    "previous-track": lambda: keys("XF86AudioPrev"),
    "back": lambda: keys("alt+Left"),
    "forward": lambda: keys("alt+Right"),
    "screenshot": lambda: keys("Print"),
    "next-wallpaper": lambda: subprocess.run([str(WALLPAPER_SCRIPT)], capture_output=True, timeout=20),
}


def perform(action, group, gesture, dry_run=False):
    record = {"gesture": gesture, "action": action, "label": ACTIONS.get(action, action),
              "at": time.time()}
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        LAST_FILE.write_text(json.dumps(record), encoding="utf-8")
    except OSError:
        pass

    log(f"{gesture} -> {action}")
    if dry_run or action == "none":
        return

    if action == "custom":
        combo = (group.get("shortcut") or {}).get(gesture.split()[-1], "").strip()
        if combo:
            keys(combo)
        return

    handler = HANDLERS.get(action)
    if handler is None:
        log(f"unknown action {action}")
        return
    try:
        handler()
    except Exception as error:
        log(f"{action} failed: {error}")


# ------------------------------------------------------------------
# Event loop
# ------------------------------------------------------------------


class DoubleTap:
    """Recognises a modifier (Ctrl or Alt) pressed and released twice on its own.

    Anything else between the presses - another key (Ctrl+C, Alt+Tab), a click
    or a scroll - means the key was used as a modifier, and the count starts
    over.
    """

    def __init__(self, names):
        self.names = names
        self.down_at = None
        self.clean = False
        self.last_tap = None
        self.other_down = 0

    def feed(self, line):
        """True when this line completes a double Ctrl."""
        key = KEY.search(line)
        if key is None:
            if POINTER_BUTTON.search(line):
                self.clean = False
                self.last_tap = None
            return False

        stamp, name, pressed = float(key.group(1)), key.group(2), key.group(4) == "pressed"
        if name not in self.names:
            self.other_down += 1 if pressed else -1
            self.other_down = max(0, self.other_down)
            if pressed:
                self.clean = False
                self.last_tap = None
            return False

        if pressed:
            self.down_at = stamp
            self.clean = self.other_down == 0
            return False

        tapped = self.clean and self.down_at is not None and stamp - self.down_at <= CTRL_TAP_SECONDS
        self.down_at = None
        if not tapped:
            self.last_tap = None
            return False
        if self.last_tap is not None and stamp - self.last_tap <= CTRL_GAP_SECONDS + CTRL_TAP_SECONDS:
            self.last_tap = None
            return True
        self.last_tap = stamp
        return False


def run(stream, settings, dry_run=False):
    dx = dy = 0.0
    fingers = 0
    swiping = False
    hold_started = None
    hold_fingers = 0
    taps = (
        (DoubleTap(CTRL_KEYS), "double_ctrl", "double Ctrl"),
        (DoubleTap(ALT_KEYS), "double_alt", "double Alt"),
    )

    for line in stream:
        if "KEYBOARD_KEY" in line or "POINTER_" in line:
            for detector, setting, label in taps:
                if detector.feed(line):
                    data = settings.current()
                    if data.get("enabled", True):
                        group = data.get("keyboard") or {}
                        threading.Thread(target=perform, daemon=True,
                                         args=(group.get(setting, "none"), group, label, dry_run)).start()
            continue

        match = EVENT.search(line)
        if not match:
            continue

        kind, phase = match.group(1), match.group(2)
        stamp = float(match.group(3))
        count = int(match.group(4))
        cancelled = bool(match.group(7))

        if kind == "HOLD":
            # A four-finger tap reaches libinput as a hold that ends quickly
            # without turning into a swipe. Three-finger taps never get here:
            # libinput turns those into a middle click.
            if phase == "BEGIN":
                hold_started, hold_fingers = stamp, count
            elif phase == "END":
                quick = hold_started is not None and stamp - hold_started <= TAP_SECONDS
                if quick and hold_fingers == 4 and not cancelled:
                    data = settings.current()
                    if data.get("enabled", True):
                        group = data.get("4") or {}
                        perform(group.get("tap", "none"), group, "4-finger tap", dry_run)
                hold_started = None
            continue

        # SWIPE
        hold_started = None
        if phase == "BEGIN":
            dx = dy = 0.0
            fingers = count
            swiping = count in (3, 4)
            continue

        if phase == "UPDATE" and swiping:
            if match.group(5) is not None:
                dx += float(match.group(5))
                dy += float(match.group(6))
            continue

        if phase == "END" and swiping:
            swiping = False
            if cancelled or not settings.current().get("enabled", True):
                continue
            if max(abs(dx), abs(dy)) < settings.threshold():
                continue
            if abs(dx) >= abs(dy):
                direction = "right" if dx > 0 else "left"
            else:
                direction = "down" if dy > 0 else "up"
            action, group = settings.action_for(fingers, direction)
            perform(action, group, f"{fingers}-finger swipe {direction}", dry_run)


# ------------------------------------------------------------------
# Diagnostics
# ------------------------------------------------------------------


def doctor():
    """Report exactly which prerequisite is missing, and the fix for it."""
    import glob
    import shutil

    ok = True

    have_libinput = shutil.which("libinput") is not None
    print(f"[{'ok' if have_libinput else 'MISSING'}] libinput-tools")
    if not have_libinput:
        print("        sudo apt install -y libinput-tools")
        ok = False

    in_group = "input" in sh("id", "-nG").split()
    print(f"[{'ok' if in_group else 'MISSING'}] membership of the input group")
    if not in_group:
        print('        sudo gpasswd -a "$USER" input')
        ok = False

    readable = [d for d in glob.glob("/dev/input/event*") if os.access(d, os.R_OK)]
    print(f"[{'ok' if readable else 'MISSING'}] readable event devices "
          f"({len(readable)} of {len(glob.glob('/dev/input/event*'))})")
    if in_group and not readable:
        print("        the group is set but this session predates it - log out and back in")
        ok = False

    has_pad = "ouchpad" in sh("xinput", "list")
    print(f"[{'ok' if has_pad else 'MISSING'}] touchpad present to X11")

    reply = sh("gdbus", "call", "--session", "-d", "org.gnome.Shell",
               "-o", "/org/adaptive/Shell", "-m", "org.adaptive.Shell.Run", "probe")
    shell_ok = reply.startswith("(")
    print(f"[{'ok' if shell_ok else 'MISSING'}] Adaptive Shell gesture actions")
    if not shell_ok:
        print("        the shell extension predates shellActions.js - reload the shell")

    return 0 if ok else 1


def status():
    """One line of JSON for the settings app: is the daemon usable?"""
    import glob
    readable = any(os.access(d, os.R_OK) for d in glob.glob("/dev/input/event*"))
    running = bool(sh("pgrep", "-f", "adaptive-gestures.py --daemon"))
    print(json.dumps({"readable": readable, "running": running}))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doctor", action="store_true",
                    help="check prerequisites and say what is missing")
    ap.add_argument("--status", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--list-actions", action="store_true",
                    help="print the actions and presets as JSON")
    ap.add_argument("--daemon", action="store_true",
                    help="run in the background (the autostart form)")
    ap.add_argument("--replay", help="parse a saved debug-events capture")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.doctor:
        return doctor()
    if args.status:
        return status()
    if args.list_actions:
        print(json.dumps({"actions": ACTIONS, "presets": PRESETS, "defaults": DEFAULTS}))
        return 0

    settings = Settings()

    if args.replay:
        with open(args.replay, encoding="utf-8") as handle:
            run(handle, settings, args.dry_run)
        return 0

    try:
        # libinput block-buffers stdout when it is a pipe, which holds every key
        # event back until ~4 KB have piled up; stdbuf makes it line-buffered.
        proc = subprocess.Popen(["stdbuf", "-oL", "libinput", "debug-events", "--show-keycodes"],
                                stdout=subprocess.PIPE, text=True, bufsize=1)
    except FileNotFoundError:
        log("libinput not installed - run: sudo apt install -y libinput-tools")
        print("libinput is not installed. Run:\n"
              "  sudo apt install -y libinput-tools\n"
              '  sudo gpasswd -a "$USER" input   # then log out and back in',
              file=sys.stderr)
        return 2

    # Stopping the service (install-gestures.sh sends SIGTERM) must take the
    # libinput reader with it, or it keeps reading input devices orphaned.
    import signal
    signal.signal(signal.SIGTERM, lambda *_args: sys.exit(0))

    log("gesture daemon started (3 and 4 fingers, double Ctrl, double Alt)")
    try:
        run(proc.stdout, settings, args.dry_run)
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
