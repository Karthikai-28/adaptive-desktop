"""Adaptive Link - the rest of the machine: Bluetooth, displays, sound
devices, services, power and temperatures, and the open windows.

What the phone's Bluetooth, Display and sound, Services and Windows screens
show and do, each through the tool that already owns it: BlueZ (bluetoothctl),
the X server (xrandr), PulseAudio (pactl), the owner's systemd (systemctl
--user), power-profiles-daemon, and the window manager (xprop, xdotool).

As in system.py, only what is listed can be asked for: a device BlueZ
knows, an output and a mode the X server offers, a sink PulseAudio has, a
unit systemd lists, a window the window manager manages. Every action
returns (done, what to say).
"""

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path


def _run(*command, timeout=8, feed=None):
    """(ok, what it printed). Never raises."""
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=timeout, input=feed, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)
    return done.returncode == 0, (done.stdout if done.returncode == 0 else done.stderr or done.stdout).strip()


def _last_line(text):
    return (text.strip().splitlines() or [""])[-1][:300]


# --------------------------------------------------------------- bluetooth

MAC = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")
BLUETOOTH_LIMIT = 20
BLUETOOTH_KINDS = {"audio-headset": "Headset", "audio-headphones": "Headphones", "audio-card": "Speaker",
                   "input-keyboard": "Keyboard", "input-mouse": "Mouse", "input-gaming": "Controller",
                   "phone": "Phone", "computer": "Computer", "input-tablet": "Tablet"}


def _bluetooth_field(text, name):
    match = re.search(rf"^\s*{name}: (.*)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def bluetooth():
    """Whether Bluetooth is on, and the devices this computer knows."""
    if not shutil.which("bluetoothctl"):
        return {"available": False, "on": False, "devices": []}
    ok, shown = _run("bluetoothctl", "show")
    if not ok or "Controller" not in shown:
        return {"available": False, "on": False, "devices": []}
    devices = []
    for line in _run("bluetoothctl", "devices")[1].splitlines()[:BLUETOOTH_LIMIT]:
        parts = line.split(None, 2)
        if len(parts) < 2 or parts[0] != "Device" or not MAC.match(parts[1]):
            continue
        info = _run("bluetoothctl", "info", parts[1])[1]
        battery = re.search(r"Battery Percentage: 0x[0-9a-fA-F]+ \((\d+)\)", info)
        devices.append({"address": parts[1], "name": _bluetooth_field(info, "Name") or (parts[2] if len(parts) > 2 else parts[1]),
                        "kind": BLUETOOTH_KINDS.get(_bluetooth_field(info, "Icon"), ""),
                        "paired": _bluetooth_field(info, "Paired") == "yes",
                        "connected": _bluetooth_field(info, "Connected") == "yes",
                        "battery": int(battery.group(1)) if battery else None})
    devices.sort(key=lambda d: (not d["connected"], not d["paired"], d["name"].casefold()))
    return {"available": True, "on": _bluetooth_field(shown, "Powered") == "yes", "devices": devices}


def bluetooth_action(action, target=""):
    if action == "power":
        if target not in ("on", "off"):
            return False, "on or off"
        done, text = _run("bluetoothctl", "power", target)
        return done and "succeeded" in text, "" if done and "succeeded" in text else _last_line(text)
    if action in ("connect", "disconnect"):
        if not any(device["address"] == target for device in bluetooth()["devices"]):
            return False, "no such device"
        done, text = _run("bluetoothctl", action, target, timeout=25)
        worked = done and ("successful" in text.lower())
        return worked, "" if worked else "it did not answer" if "Failed" in text or not text else _last_line(text)
    return False, "unknown action"


# ----------------------------------------------------------------- display

OUTPUT_LINE = re.compile(r"^(\S+) (connected|disconnected)( primary)?(?: (\d+)x(\d+)\+(-?\d+)\+(-?\d+))?")
MODE_LINE = re.compile(r"^\s+(\d+x\d+)\s+(.*)$")
MODE_LIMIT = 12
GSD_POWER = ("org.gnome.SettingsDaemon.Power", "/org/gnome/SettingsDaemon/Power")


def parse_xrandr(text):
    """The outputs xrandr lists: [{name, connected, on, primary, mode, modes}]."""
    outputs = []
    for line in text.splitlines():
        head = OUTPUT_LINE.match(line)
        if head:
            outputs.append({"name": head.group(1), "connected": head.group(2) == "connected",
                            "primary": bool(head.group(3)), "on": head.group(4) is not None,
                            "mode": f"{head.group(4)}x{head.group(5)}" if head.group(4) else "", "modes": [],
                            # Where it lies on the whole screen: x, y, width, height.
                            "at": [int(head.group(n)) for n in (6, 7, 4, 5)] if head.group(4) else []})
            continue
        mode = MODE_LINE.match(line)
        if mode and outputs:
            current = outputs[-1]
            if "*" in mode.group(2):
                current["mode"] = mode.group(1)
            if mode.group(1) not in current["modes"] and len(current["modes"]) < MODE_LIMIT:
                current["modes"].append(mode.group(1))
    return [output for output in outputs if output["connected"]]


def region(name):
    """(x, y, width, height) of one display on the whole screen, or None."""
    ok, out = _run("xrandr", "--query")
    for output in parse_xrandr(out) if ok else []:
        if output["name"] == name and output["at"]:
            return tuple(output["at"])
    return None


_made = None   # the display made for the phone, while there is one (virtual_display.py)


def _outputs_now():
    ok, out = _run("xrandr", "--query")
    return [line.split()[0] for line in out.splitlines() if ok and " connected" in line]


def extend(size):
    """Make the phone another display, to the right of the main one.
    Returns (done, the new display's name or why not).

    The display is one made for the purpose (the evdi module, where it is
    installed): the desktop is told a monitor of the phone's size has been
    plugged in, and extends onto it as it would onto any other.
    """
    global _made
    match = re.fullmatch(r"(\d{3,4})x(\d{3,4})", str(size))
    if not match:
        return False, "a size like 1280x800"
    width, height = int(match.group(1)), int(match.group(2))
    import virtual_display
    if not virtual_display.available():
        return False, ("this computer has no display to spare: run scripts/install-link-display.sh on it once, "
                       "then restart the link")
    if _made is not None:
        unextend("")
    before = set(_outputs_now())
    lit = [output for output in display()["outputs"] if output["on"]]
    made = virtual_display.VirtualDisplay()
    if not made.plug_in(width, height):
        return False, "the display could not be made"
    _made = made
    # The new card's output is the driver's to draw on once it is told so;
    # then it appears as one more connected display.
    name = ""
    for _ in range(20):
        providers = _run("xrandr", "--listproviders")[1]
        for line in providers.splitlines():
            found = re.match(r"Provider (\d+):.*name:(\S+)", line)
            if found and "evdi" in found.group(2).lower() or (found and found.group(1) != "0" and "Sink Output" in line):
                _run("xrandr", "--setprovideroutputsource", found.group(1), "0")
        new = [output for output in _outputs_now() if output not in before]
        if new:
            name = new[0]
            break
        time.sleep(0.25)
    if not name:
        unextend("")
        return False, "the display was made, but the desktop did not see it"
    main = next((output["name"] for output in lit if output["primary"]), lit[0]["name"] if lit else "")
    done, text = _run("xrandr", "--output", name, "--auto", *(("--right-of", main) if main else ()))
    if not done:
        unextend("")
        return False, _last_line(text)
    return True, name


def unextend(name):
    """Take the phone's display away again: the monitor is unplugged, and
    the desktop closes up as it does when any display goes."""
    global _made
    if _made is None:
        return False, "the phone is not a display just now"
    if name and re.fullmatch(r"[A-Za-z0-9-]{1,30}", name):
        _run("xrandr", "--output", name, "--off")
    _made.unplug()
    _made = None
    return True, ""


def _brightness():
    """The built-in screen's brightness as GNOME holds it, or None."""
    ok, out = _run("gdbus", "call", "--session", "--dest", GSD_POWER[0], "--object-path", GSD_POWER[1],
                   "--method", "org.freedesktop.DBus.Properties.Get", GSD_POWER[0] + ".Screen", "Brightness", timeout=3)
    match = re.search(r"<(-?\d+)>", out) if ok else None
    return int(match.group(1)) if match and int(match.group(1)) >= 0 else None


def display():
    ok, out = _run("xrandr", "--query")
    return {"outputs": parse_xrandr(out) if ok else [], "brightness": _brightness()}


def display_action(action, target="", value=""):
    if action == "brightness":
        if not value.isdigit() or not 1 <= int(value) <= 100:
            return False, "a number from 1 to 100"
        done, text = _run("gdbus", "call", "--session", "--dest", GSD_POWER[0], "--object-path", GSD_POWER[1],
                          "--method", "org.freedesktop.DBus.Properties.Set", GSD_POWER[0] + ".Screen", "Brightness",
                          f"<int32 {int(value)}>", timeout=3)
        return done, "" if done else "this screen's brightness cannot be set"
    if action == "extend":
        return extend(value)
    if action == "unextend":
        return unextend(target)
    outputs = display()["outputs"]
    output = next((o for o in outputs if o["name"] == target), None)
    if output is None:
        return False, "no such display"
    if action == "mode":
        if value not in output["modes"]:
            return False, "that display does not offer that size"
        done, text = _run("xrandr", "--output", target, "--mode", value)
    elif action == "off":
        if not any(o["on"] for o in outputs if o["name"] != target):
            return False, "it is the only display that is on"
        done, text = _run("xrandr", "--output", target, "--off")
    elif action == "on":
        done, text = _run("xrandr", "--output", target, "--auto")
    elif action == "primary":
        done, text = _run("xrandr", "--output", target, "--primary")
    else:
        return False, "unknown action"
    return done, "" if done else _last_line(text)


# ------------------------------------------------------------------- sound

def _pactl_list(kind):
    ok, out = _run("pactl", "-f", "json", "list", kind)
    try:
        found = json.loads(out) if ok else []
    except ValueError:
        return []
    return found if isinstance(found, list) else []


def _percent(entry):
    """The loudest channel's volume, as a percentage."""
    volumes = entry.get("volume") if isinstance(entry.get("volume"), dict) else {}
    found = [int(str(v.get("value_percent", "0")).rstrip("%") or 0) for v in volumes.values() if isinstance(v, dict)]
    return max(found, default=0)


def sound():
    """Where sound comes out and goes in: the devices, and which is in use."""
    chosen = {kind: _run("pactl", f"get-default-{kind}")[1].strip() for kind in ("sink", "source")}

    def devices(kind, plural):
        return [{"name": entry.get("name", ""), "label": entry.get("description") or entry.get("name", ""),
                 "volume": _percent(entry), "muted": bool(entry.get("mute")),
                 "default": entry.get("name") == chosen[kind]}
                for entry in _pactl_list(plural)
                # A sink's "monitor" is its own sound played back, not a microphone.
                if entry.get("name") and not (kind == "source" and str(entry.get("name")).endswith(".monitor"))]

    return {"outputs": devices("sink", "sinks"), "inputs": devices("source", "sources")}


def sound_action(action, target="", value=""):
    kind = "sink" if action.startswith("output") else "source" if action.startswith("input") else ""
    now = sound()
    if not kind or not any(device["name"] == target for device in now["outputs" if kind == "sink" else "inputs"]):
        return False, "no such device"
    if action.endswith("-use"):
        done, text = _run("pactl", f"set-default-{kind}", target)
    elif action.endswith("-volume"):
        if not value.isdigit() or int(value) > 100:
            return False, "a number from 0 to 100"
        done, text = _run("pactl", f"set-{kind}-volume", target, f"{int(value)}%")
    elif action.endswith("-mute"):
        if value not in ("on", "off"):
            return False, "on or off"
        done, text = _run("pactl", f"set-{kind}-mute", target, "1" if value == "on" else "0")
    else:
        return False, "unknown action"
    return done, "" if done else _last_line(text)


# ---------------------------------------------------------------- services

SERVICE_LIMIT = 200
OWN_UNIT = "adaptive-link.service"
UNIT_NAME = re.compile(r"^[A-Za-z0-9:_.@\\-]{1,200}\.service$")


def services():
    """The owner's own services (systemctl --user): what each is and whether it runs."""
    ok, out = _run("systemctl", "--user", "list-units", "--type=service", "--all", "--output=json", "--no-pager")
    try:
        units = json.loads(out) if ok else []
    except ValueError:
        units = []
    found = [{"name": unit.get("unit", ""), "label": unit.get("description", ""),
              "running": unit.get("active") == "active", "state": unit.get("sub", ""),
              "failed": unit.get("active") == "failed", "own": unit.get("unit") == OWN_UNIT}
             for unit in units if isinstance(unit, dict) and UNIT_NAME.match(str(unit.get("unit", "")))
             and unit.get("load") == "loaded"]
    found.sort(key=lambda unit: (not unit["failed"], not unit["running"], unit["name"]))
    return found[:SERVICE_LIMIT]


def service_action(action, target):
    if action not in ("start", "stop", "restart"):
        return False, "unknown action"
    if not any(unit["name"] == target for unit in services()):
        return False, "no such service"
    if target == OWN_UNIT and action == "stop":
        return False, "that is Adaptive Link itself; turn it off from the computer"
    if target == OWN_UNIT:
        # It ends this very process: started apart, so the answer gets out first.
        subprocess.Popen(["sh", "-c", f"sleep 1; systemctl --user restart {OWN_UNIT}"], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True, "Restarting; the phone reconnects in a moment"
    done, text = _run("systemctl", "--user", action, target, timeout=30)
    return done, "" if done else _last_line(text)


def service_log(target, lines=40):
    """The last lines a service wrote."""
    if not any(unit["name"] == target for unit in services()):
        return False, "no such service"
    done, text = _run("journalctl", "--user", "-u", target, "-n", str(lines), "--no-pager", "-o", "short")
    return done, text[-6000:] if done else _last_line(text)


# ------------------------------------------------ power and temperatures

POWER_ROOT = Path("/sys/class/power_supply")
HWMON_ROOT = Path("/sys/class/hwmon")
SENSOR_NAMES = {"coretemp": "Processor", "k10temp": "Processor", "zenpower": "Processor", "acpitz": "Board",
                "nvme": "Drive", "amdgpu": "Graphics", "nouveau": "Graphics", "iwlwifi_1": "Wi-Fi"}


def _read(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _number(path):
    text = _read(path)
    return int(text) if text.lstrip("-").isdigit() else None


def battery(root=POWER_ROOT):
    """The battery in detail, or None on a machine without one."""
    try:
        names = sorted(name for name in os.listdir(root) if name.startswith("BAT"))
    except OSError:
        return None
    for name in names:
        folder = Path(root, name)
        percent = _number(folder / "capacity")
        if percent is None:
            continue
        state = _read(folder / "status")
        # Either energy (µWh, µW) or charge (µAh, µA), by the battery's maker.
        now = _number(folder / "energy_now") or _number(folder / "charge_now")
        full = _number(folder / "energy_full") or _number(folder / "charge_full")
        design = _number(folder / "energy_full_design") or _number(folder / "charge_full_design")
        rate = abs(_number(folder / "power_now") or _number(folder / "current_now") or 0)
        minutes = None
        if rate and now is not None and full:
            left = (full - now) if state == "Charging" else now
            minutes = max(0, int(left * 60 / rate)) if state in ("Charging", "Discharging") else None
        return {"percent": percent, "state": state, "charging": state in ("Charging", "Full"),
                "minutes": minutes, "health": min(100, round(full * 100 / design)) if full and design else None,
                "cycles": _number(folder / "cycle_count")}
    return None


def temperatures(root=HWMON_ROOT):
    """The hottest reading of each sensor, and the fans that report a speed."""
    sensors, fans = [], []
    try:
        folders = sorted(root.iterdir())
    except OSError:
        return sensors, fans
    for folder in folders:
        name = _read(folder / "name")
        readings = [value / 1000 for value in (_number(path) for path in folder.glob("temp*_input"))
                    if value is not None and 0 < value < 150_000]
        if readings:
            sensors.append({"name": SENSOR_NAMES.get(name, name or folder.name), "celsius": round(max(readings), 1)})
        for path in sorted(folder.glob("fan*_input")):
            speed = _number(path)
            if speed:
                fans.append({"name": _read(path.with_name(path.name.replace("_input", "_label"))) or "Fan", "rpm": speed})
    # One line per kind of sensor: the hottest of each.
    hottest = {}
    for sensor in sensors:
        if sensor["celsius"] > hottest.get(sensor["name"], {"celsius": -1})["celsius"]:
            hottest[sensor["name"]] = sensor
    return sorted(hottest.values(), key=lambda s: -s["celsius"]), fans


def _profiles():
    """(the power profile in use, the ones offered)."""
    if not shutil.which("powerprofilesctl"):
        return "", []
    ok, current = _run("powerprofilesctl", "get", timeout=3)
    listed = re.findall(r"^[ *]+([a-z-]+):\s*$", _run("powerprofilesctl", "list", timeout=3)[1], re.MULTILINE)
    return (current.strip() if ok else ""), listed


def health():
    sensors, fans = temperatures()
    profile, offered = _profiles()
    return {"battery": battery(), "temperatures": sensors, "fans": fans, "profile": profile, "profiles": offered}


def health_action(action, target=""):
    if action != "profile":
        return False, "unknown action"
    if target not in _profiles()[1]:
        return False, "no such power profile"
    done, text = _run("powerprofilesctl", "set", target, timeout=5)
    return done, "" if done else _last_line(text)


# ----------------------------------------------------------------- windows

WINDOW_LIMIT = 60
WINDOW_ID = re.compile(r"0x[0-9a-fA-F]+")
MOVES = {"left": "super+shift+Left", "right": "super+shift+Right"}


def _xprop(*args):
    return _run("xprop", *args, timeout=3)[1]


def _text(props, name):
    match = re.search(rf'^{name}\(\w+\) = "(.*)"$', props, re.MULTILINE)
    return match.group(1).replace('\\"', '"') if match else ""


def windows():
    """The windows that are open, the one in front first."""
    root = _xprop("-root", "_NET_CLIENT_LIST_STACKING", "_NET_ACTIVE_WINDOW")
    stacking = re.search(r"_NET_CLIENT_LIST_STACKING\(WINDOW\): window id # (.*)$", root, re.MULTILINE)
    active = re.search(r"_NET_ACTIVE_WINDOW\(WINDOW\): window id # (0x[0-9a-fA-F]+)", root)
    front = int(active.group(1), 16) if active else 0
    found = []
    for wid in reversed(WINDOW_ID.findall(stacking.group(1)) if stacking else []):
        props = _xprop("-id", wid, "_NET_WM_NAME", "WM_NAME", "WM_CLASS", "_NET_WM_STATE", "_NET_WM_WINDOW_TYPE")
        kind = re.search(r"_NET_WM_WINDOW_TYPE\(ATOM\) = (.*)$", props, re.MULTILINE)
        if kind and "_NET_WM_WINDOW_TYPE_NORMAL" not in kind.group(1) and "DIALOG" not in kind.group(1):
            continue   # the desktop itself, docks and panels
        state = re.search(r"_NET_WM_STATE\(ATOM\) = (.*)$", props, re.MULTILINE)
        app = re.search(r'WM_CLASS\(STRING\) = "[^"]*", "([^"]*)"', props)
        if state and "SKIP_TASKBAR" in state.group(1):
            continue
        found.append({"id": int(wid, 16), "title": (_text(props, "_NET_WM_NAME") or _text(props, "WM_NAME"))[:200],
                      "app": app.group(1) if app else "", "active": int(wid, 16) == front,
                      "minimized": bool(state and "_NET_WM_STATE_HIDDEN" in state.group(1)),
                      "maximized": bool(state and "MAXIMIZED_VERT" in state.group(1))})
        if len(found) >= WINDOW_LIMIT:
            break
    return found


def window_action(action, target, value=""):
    try:
        wid = int(target)
    except (TypeError, ValueError):
        return False, "no such window"
    if not any(window["id"] == wid for window in windows()):
        return False, "no such window"
    wid = str(wid)
    if action == "show":
        done, text = _run("xdotool", "windowactivate", "--sync", wid)
    elif action == "minimize":
        done, text = _run("xdotool", "windowminimize", wid)
    elif action == "close":
        # Asked to close, as its own close button would: it may ask to save.
        done, text = _run("xdotool", "windowactivate", "--sync", wid, "key", "--clearmodifiers", "alt+F4")
    elif action == "move":
        if value not in MOVES:
            return False, "left or right"
        done, text = _run("xdotool", "windowactivate", "--sync", wid, "key", "--clearmodifiers", MOVES[value])
    else:
        return False, "unknown action"
    return done, "" if done else _last_line(text)


# ------------------------------------------------------------- one way in

READ = {"bluetooth": bluetooth, "display": display, "sound": sound, "health": health,
        "services": lambda: {"services": services()}, "windows": lambda: {"windows": windows()}}
ACT = {"bluetooth": lambda action, target, value: bluetooth_action(action, target),
       "display": display_action, "sound": sound_action,
       "health": lambda action, target, value: health_action(action, target),
       "services": lambda action, target, value: service_action(action, target),
       "windows": window_action}
# The owner's switch each one goes with: seeing and changing.
SWITCH = {"services": ("allow_exec", "allow_exec"), "health": (None, "allow_power"),
          "windows": ("allow_input", "allow_input")}
