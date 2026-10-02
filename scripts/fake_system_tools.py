#!/usr/bin/env python3
"""NetworkManager and UDisks, as far as the link's checks go.

verify-link.py and verify-link-android.py put this on the daemon's PATH as
`nmcli` and `udisksctl`, so the checks can turn Wi-Fi off, join networks and
unmount drives without touching the machine they run on. What it is asked is
written to FAKE_TOOLS_DIR/calls.log; the network's state is kept in
FAKE_TOOLS_DIR/network.json.
"""

import json
import os
import sys
from pathlib import Path

DIR = Path(os.environ.get("FAKE_TOOLS_DIR", "."))   # set for the daemon, which is who runs the stand-ins
STATE = DIR / "network.json"
DEVICE = "wlan-check"
# name: (signal, security, password)
IN_RANGE = {"Home": (80, "WPA2", "home-password"), "Cafe: Open": (55, "", ""), "Other": (40, "WPA2", "correct-horse")}


def install(folder):
    """Put the stand-ins in `folder`, for the front of a PATH."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("nmcli", "udisksctl"):
        link = folder / name
        if not link.exists():
            link.symlink_to(Path(__file__).resolve())
    return folder


def load():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {"radio": True, "active": "Home", "device": True, "saved": ["Home"], "vpn": False}


def terse(*fields):
    return ":".join(str(field).replace("\\", "\\\\").replace(":", "\\:") for field in fields)


def nmcli(args, state):
    args = [a for a in args if a not in ("-t", "--ask")]
    for option in ("--wait", "-f"):
        if option in args:
            del args[args.index(option):args.index(option) + 2]
    on_air = state["radio"] and state["device"]
    if args[:2] == ["radio", "wifi"]:
        if len(args) == 2:
            print("enabled" if state["radio"] else "disabled")
        else:
            state["radio"] = args[2] == "on"
            state["active"] = state["active"] if state["radio"] else ""
    elif args[:2] == ["con", "show"]:
        for name in state["saved"]:
            print(terse(name, "802-11-wireless", "yes" if name == state["active"] else "no"))
        print(terse("Work VPN", "vpn", "yes" if state["vpn"] else "no"))
    elif args[:3] == ["dev", "wifi", "list"]:
        for name, (strength, security, _password) in IN_RANGE.items() if state["radio"] else ():
            print(terse("*" if name == state["active"] else " ", name, strength, "5180 MHz", "270 Mbit/s", security or "--"))
    elif args[:3] == ["dev", "wifi", "rescan"]:
        pass
    elif args[:3] == ["dev", "wifi", "connect"]:
        name = args[3]
        if IN_RANGE[name][2] and sys.stdin.readline().rstrip("\n") != IN_RANGE[name][2]:
            state["saved"].append(name)   # as the real one leaves a half-made one behind
            STATE.write_text(json.dumps(state))
            sys.exit("Error: Connection activation failed: Secrets were required, but not provided.")
        state["saved"].append(name)
        state["active"] = name
    elif args[:3] == ["con", "up", "id"]:
        if args[3] == "Work VPN":
            state["vpn"] = True
        elif args[3] in state["saved"] and on_air:
            state["active"] = args[3]
        else:
            sys.exit("Error: unknown connection.")
    elif args[:3] == ["con", "down", "id"]:
        if args[3] == "Work VPN":
            state["vpn"] = False
        elif args[3] == state["active"]:
            state["active"] = ""
    elif args[:3] == ["con", "delete", "id"]:
        state["saved"] = [name for name in state["saved"] if name != args[3]]
    elif args[:2] in (["dev", "disconnect"], ["dev", "connect"]):
        state["device"] = args[1] == "connect"
        state["active"] = "Home" if state["device"] and state["radio"] else ""
    elif args == ["dev"]:
        print(terse(DEVICE, "connected" if state["active"] else "disconnected", state["active"]))
        print(terse("lo", "unmanaged", ""))
    else:
        sys.exit(f"fake nmcli: not understood: {args}")
    STATE.write_text(json.dumps(state))


def main():
    tool = Path(sys.argv[0]).name
    with (DIR / "calls.log").open("a") as log:
        log.write(json.dumps([tool, *sys.argv[1:]]) + "\n")
    if tool == "nmcli":
        nmcli(sys.argv[1:], load())
    else:
        sys.exit("fake udisksctl: nothing here is to be mounted")


if __name__ == "__main__":
    main()
