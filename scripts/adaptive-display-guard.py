#!/usr/bin/env python3
"""Keep windows off screens that are not there.

An HDMI or DisplayPort port can report `connected` with no monitor on the end
of it - no EDID, no physical size, one generic 1024x768 mode. X believes it,
mutter lays out a screen there, and windows get placed on a monitor nobody can
see. They are open and running and completely unreachable: the symptom is
"I disconnected the external display and now Chrome will not come back".

A real monitor always publishes an EDID. An output that is connected and
publishes none is a ghost, and this turns it off.

    ./scripts/adaptive-display-guard.py            # turn ghosts off
    ./scripts/adaptive-display-guard.py --check    # report, change nothing

Opt out - some KVMs and cheap adapters do drop EDID for a real screen:

    touch ~/.config/adaptive-desktop/allow-phantom-displays
"""

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

LOG_FILE = Path.home() / ".local/state/adaptive-desktop/display-guard.log"
OPT_OUT = Path.home() / ".config/adaptive-desktop/allow-phantom-displays"

HEADER = re.compile(
    r"^(?P<name>\S+) (?P<state>connected|disconnected)"
    r"(?P<primary> primary)?"
    r"(?: (?P<geom>\d+x\d+\+\d+\+\d+))?"
)


def log(message):
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%F %T')} {message}\n")
    except Exception:
        pass


def outputs():
    """Every output X knows about, with whether it published an EDID."""
    try:
        raw = subprocess.run(
            ["xrandr", "--props"], capture_output=True, text=True, timeout=15
        ).stdout
    except Exception as exc:
        print(f"xrandr failed: {exc}", file=sys.stderr)
        return []

    found = []
    current = None

    for line in raw.splitlines():
        match = HEADER.match(line)
        if match:
            current = {
                "name": match.group("name"),
                "connected": match.group("state") == "connected",
                "primary": bool(match.group("primary")),
                "enabled": bool(match.group("geom")),
                "geometry": match.group("geom") or "",
                "edid": False,
            }
            found.append(current)
            continue

        # Properties are indented under the output they belong to.
        if current is not None and line.startswith("\t") and "EDID:" in line:
            current["edid"] = True

    return found


def phantoms(found):
    return [o for o in found if o["connected"] and not o["edid"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="report ghost outputs without changing anything")
    args = ap.parse_args()

    if not os.environ.get("DISPLAY"):
        print("no DISPLAY; nothing to do")
        return 0

    found = outputs()
    if not found:
        return 0

    ghosts = phantoms(found)
    enabled = [o for o in found if o["enabled"]]

    for o in found:
        if not o["connected"]:
            continue
        mark = "ghost" if o in ghosts else "real "
        where = o["geometry"] or "off"
        print(f"  {mark} {o['name']:10s} {where}"
              f"{'  (primary)' if o['primary'] else ''}")

    live_ghosts = [o for o in ghosts if o["enabled"]]

    if not live_ghosts:
        return 0

    if args.check:
        for o in live_ghosts:
            print(f"\n{o['name']} is enabled but published no EDID - windows "
                  f"placed there are invisible")
        return 1

    if OPT_OUT.exists():
        print(f"\n{OPT_OUT} exists; leaving ghost outputs alone")
        return 0

    for ghost in live_ghosts:
        # Two things that must never happen: blanking the built-in panel
        # because it came up without an EDID, and turning off the last screen.
        if ghost["primary"]:
            print(f"\n{ghost['name']} is the primary output; leaving it on")
            log(f"declined to disable primary ghost {ghost['name']}")
            continue

        if len(enabled) <= 1:
            print(f"\n{ghost['name']} is the only enabled output; leaving it on")
            log(f"declined to disable only output {ghost['name']}")
            continue

        print(f"\nturning off {ghost['name']}: connected but no EDID, so "
              f"nothing is plugged into it")
        log(f"disabling ghost output {ghost['name']} "
            f"(was {ghost['geometry'] or 'off'})")

        subprocess.run(["xrandr", "--output", ghost["name"], "--off"],
                       capture_output=True)
        enabled = [o for o in enabled if o is not ghost]

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
