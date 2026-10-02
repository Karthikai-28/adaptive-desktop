#!/usr/bin/env python3
"""NetworkManager, UDisks, BlueZ, PulseAudio, systemd and the power
profiles, as far as the link's checks go.

verify-link.py and verify-link-android.py put this on the daemon's PATH under
each tool's name, so the checks can turn Wi-Fi and Bluetooth off, join
networks, unmount drives, change the volume and stop services without
touching the machine they run on. What it is asked is written to
FAKE_TOOLS_DIR/calls.log; the state is kept in FAKE_TOOLS_DIR/network.json
and machine.json.
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
    for name in TOOLS:
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
    if args[:1] == ["-g"]:
        print(state.get("wake", {}).get(args[-1], "default"))
        return
    if args[:3] == ["con", "modify", "id"]:
        state.setdefault("wake", {})[args[3]] = args[5]
        STATE.write_text(json.dumps(state))
        return
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


MACHINE = DIR / "machine.json"
SPEAKER, HEADSET, MICROPHONE = "speaker.check", "headset.check", "microphone.check"


def machine():
    try:
        return json.loads(MACHINE.read_text())
    except (OSError, ValueError):
        return {"bluetooth": True, "connected": [], "sink": SPEAKER, "source": MICROPHONE,
                "volume": {SPEAKER: 50, HEADSET: 30, MICROPHONE: 80}, "muted": [],
                "running": ["sync.service", "adaptive-link.service"], "profile": "balanced"}


def bluetoothctl(args, state):
    devices = {"AA:BB:CC:00:00:01": ("Check Headphones", "audio-headphones"), "AA:BB:CC:00:00:02": ("Check Mouse", "input-mouse")}
    if args == ["show"]:
        print(f"Controller 00:11:22:33:44:55 (public)\n\tName: check\n\tPowered: {'yes' if state['bluetooth'] else 'no'}")
    elif args == ["devices"]:
        for address, (name, _icon) in devices.items():
            print(f"Device {address} {name}")
    elif args[:1] == ["info"] and args[1] in devices:
        name, icon = devices[args[1]]
        print(f"Device {args[1]} (public)\n\tName: {name}\n\tIcon: {icon}\n\tPaired: yes\n"
              f"\tConnected: {'yes' if args[1] in state['connected'] else 'no'}\n\tBattery Percentage: 0x46 (70)")
    elif args[:1] == ["power"]:
        state["bluetooth"] = args[1] == "on"
        state["connected"] = state["connected"] if state["bluetooth"] else []
        print("Changing power succeeded")
    elif args[:1] in (["connect"], ["disconnect"]) and args[1] in devices:
        if args[0] == "connect" and not state["bluetooth"]:
            sys.exit("Failed to connect: org.bluez.Error.NotReady")
        state["connected"] = [a for a in state["connected"] if a != args[1]] + ([args[1]] if args[0] == "connect" else [])
        print("Connection successful" if args[0] == "connect" else "Successful disconnected")
    else:
        sys.exit(f"fake bluetoothctl: not understood: {args}")


def pactl(args, state):
    def entry(name, label):
        percent = f"{state['volume'][name]}%"
        return {"name": name, "description": label, "mute": name in state["muted"],
                "volume": {"front-left": {"value_percent": percent}, "front-right": {"value_percent": percent}}}

    def named(name):
        return state["sink"] if name == "@DEFAULT_SINK@" else state["source"] if name == "@DEFAULT_SOURCE@" else name

    if args[:3] == ["-f", "json", "list"]:
        print(json.dumps([entry(SPEAKER, "Check Speakers"), entry(HEADSET, "Check Headset")] if args[3] == "sinks"
                         else [entry(MICROPHONE, "Check Microphone"),
                               {"name": SPEAKER + ".monitor", "description": "Monitor of Check Speakers", "mute": False}]))
    elif args[0] in ("get-default-sink", "get-default-source"):
        print(state[args[0].rsplit("-", 1)[1]])
    elif args[0] in ("set-default-sink", "set-default-source") and args[1] in state["volume"]:
        state[args[0].rsplit("-", 1)[1]] = args[1]
    elif args[0] in ("set-sink-volume", "set-source-volume"):
        now = state["volume"][named(args[1])]
        asked = args[2].rstrip("%")
        state["volume"][named(args[1])] = max(0, min(150, now + int(asked) if asked[0] in "+-" else int(asked)))
    elif args[0] in ("set-sink-mute", "set-source-mute"):
        name = named(args[1])
        on = name not in state["muted"] if args[2] == "toggle" else args[2] == "1"
        state["muted"] = [m for m in state["muted"] if m != name] + ([name] if on else [])
    elif args[0] == "get-sink-volume":
        print(f"Volume: front-left: 32768 /  {state['volume'][named(args[1])]}% / -18.06 dB")
    elif args[0] == "get-sink-mute":
        print("Mute: " + ("yes" if named(args[1]) in state["muted"] else "no"))
    else:
        sys.exit(f"fake pactl: not understood: {args}")


def systemctl(args, state):
    units = {"sync.service": "Check: keep files in step", "backup.service": "Check: nightly backup",
             "adaptive-link.service": "Adaptive Link"}
    if args[:1] != ["--user"]:
        sys.exit("fake systemctl: only the owner's own services are here")   # never the machine's power
    args = args[1:]
    if args[:1] == ["list-units"]:
        failed = state.get("failed", [])
        print(json.dumps([{"unit": name, "load": "loaded", "description": label,
                           "active": "failed" if name in failed else "active" if name in state["running"] else "inactive",
                           "sub": "failed" if name in failed else "running" if name in state["running"] else "dead"}
                          for name, label in units.items()]))
    elif args[0] in ("start", "stop", "restart") and args[1] in units:
        state["running"] = [u for u in state["running"] if u != args[1]] + ([] if args[0] == "stop" else [args[1]])
    else:
        sys.exit(f"fake systemctl: not understood: {args}")


def powerprofilesctl(args, state):
    profiles = ("performance", "balanced", "power-saver")
    if args == ["get"]:
        print(state["profile"])
    elif args == ["list"]:
        for name in profiles:
            print(f"{'*' if name == state['profile'] else ' '} {name}:\n    Driver:     check\n")
    elif args[:1] == ["set"] and args[1] in profiles:
        state["profile"] = args[1]
    else:
        sys.exit(f"fake powerprofilesctl: not understood: {args}")


def xdg_open(args, _state):
    """Opens nothing: a browser started by a check would outlive it."""


TOOLS = {"nmcli": None, "udisksctl": None, "bluetoothctl": bluetoothctl, "pactl": pactl, "systemctl": systemctl,
         "powerprofilesctl": powerprofilesctl, "xdg-open": xdg_open}


def main():
    tool = Path(sys.argv[0]).name
    with (DIR / "calls.log").open("a") as log:
        log.write(json.dumps([tool, *sys.argv[1:]]) + "\n")
    if tool == "nmcli":
        nmcli(sys.argv[1:], load())
    elif TOOLS.get(tool):
        state = machine()
        TOOLS[tool](sys.argv[1:], state)
        MACHINE.write_text(json.dumps(state))
    else:
        sys.exit(f"fake {tool}: nothing here for it to do")


if __name__ == "__main__":
    main()
