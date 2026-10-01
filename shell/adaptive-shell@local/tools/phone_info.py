#!/usr/bin/env python3
"""Paired phones, as JSON for the shell's Network panel.

    phone_info.py list                 paired phones from KDE Connect or GSConnect
    phone_info.py ring <backend> <id>  make the phone ring
    phone_info.py send <backend> <id>  pick a file and send it to the phone
    phone_info.py clipboard <backend> <id>
                                       put this computer's clipboard on the phone
    phone_info.py clipboard-first      the same, to the first phone in reach

Two backends, whichever is running: the KDE Connect daemon
(`sudo apt install kdeconnect`) or the GSConnect GNOME extension, which speaks
the same protocol to the same phone app. Both are asked over the session bus;
nothing here talks to the network itself.

Battery level comes from KDE Connect only. GSConnect keeps it inside the
extension, not on the bus.
"""

import json
import re
import shutil
import subprocess
import sys

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

TIMEOUT_MS = 1500
KDE = "org.kde.kdeconnect"
GSC = "org.gnome.Shell.Extensions.GSConnect"
GSC_PATH = "/org/gnome/Shell/Extensions/GSConnect"
GSC_DEVICE = GSC + ".Device"
DEVICE_ID = re.compile(r"^[\w-]+$")


def bus():
    return Gio.bus_get_sync(Gio.BusType.SESSION, None)


def call(name, path, interface, method, params=None, reply=None):
    try:
        result = bus().call_sync(name, path, interface, method, params,
                                 GLib.VariantType(reply) if reply else None,
                                 Gio.DBusCallFlags.NO_AUTO_START, TIMEOUT_MS, None)
        return result.unpack() if result is not None else ()
    except GLib.Error:
        return None


def has_owner(name):
    owned = call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                 "NameHasOwner", GLib.Variant("(s)", (name,)), "(b)")
    return bool(owned and owned[0])


def kde_battery(device_id):
    path = f"/modules/kdeconnect/devices/{device_id}/battery"
    props = call(KDE, path, "org.freedesktop.DBus.Properties", "GetAll",
                 GLib.Variant("(s)", ("org.kde.kdeconnect.device.battery",)), "(a{sv})")
    if props and "charge" in props[0]:
        return props[0].get("charge"), props[0].get("isCharging")
    # KDE Connect before 21.x: methods on the device object itself.
    old = f"/modules/kdeconnect/devices/{device_id}"
    charge = call(KDE, old, "org.kde.kdeconnect.device.battery", "charge", None, "(i)")
    charging = call(KDE, old, "org.kde.kdeconnect.device.battery", "isCharging", None, "(b)")
    return (charge[0] if charge else None), (charging[0] if charging else None)


def kde_devices():
    ids = call(KDE, "/modules/kdeconnect", "org.kde.kdeconnect.daemon", "devices",
               GLib.Variant("(bb)", (False, True)), "(as)")
    devices = []
    for device_id in (ids[0] if ids else []):
        if not DEVICE_ID.match(device_id):
            continue
        props = call(KDE, f"/modules/kdeconnect/devices/{device_id}",
                     "org.freedesktop.DBus.Properties", "GetAll",
                     GLib.Variant("(s)", ("org.kde.kdeconnect.device",)), "(a{sv})")
        info = props[0] if props else {}
        charge, charging = kde_battery(device_id)
        devices.append({
            "id": device_id,
            "name": info.get("name") or device_id,
            "type": info.get("type") or "phone",
            "reachable": bool(info.get("isReachable")),
            "battery": charge if isinstance(charge, int) and charge >= 0 else None,
            "charging": bool(charging),
        })
    return devices


def gsconnect_devices():
    managed = call(GSC, GSC_PATH, "org.freedesktop.DBus.ObjectManager",
                   "GetManagedObjects", None, "(a{oa{sa{sv}}})")
    devices = []
    for path, interfaces in (managed[0] if managed else {}).items():
        info = interfaces.get(GSC_DEVICE)
        if not info or not info.get("Paired"):
            continue
        devices.append({
            "id": path.rsplit("/", 1)[-1],
            "name": info.get("Name") or "Phone",
            "type": info.get("Type") or "phone",
            "reachable": bool(info.get("Connected")),
            "battery": None,
            "charging": False,
        })
    return devices


def list_devices():
    if has_owner(KDE):
        backend, devices = "kdeconnect", kde_devices()
    elif has_owner(GSC):
        backend, devices = "gsconnect", gsconnect_devices()
    else:
        return {"backend": None, "devices": []}
    devices.sort(key=lambda d: (not d["reachable"], d["name"].casefold()))
    return {"backend": backend, "devices": devices}


def gsconnect_action(device_id, action):
    path = f"{GSC_PATH}/Device/{device_id}"
    return call(GSC, path, "org.gtk.Actions", "Activate",
                GLib.Variant("(sava{sv})", (action, [], {})), None) is not None


def ring(backend, device_id):
    if backend == "kdeconnect":
        ok = subprocess.run(["kdeconnect-cli", "-d", device_id, "--ring"],
                            capture_output=True, timeout=10).returncode == 0
    else:
        ok = gsconnect_action(device_id, "ring")
    return {"ok": ok}


def send(backend, device_id):
    if backend == "gsconnect":
        # GSConnect has its own chooser, which also handles links and text.
        return {"ok": gsconnect_action(device_id, "shareDialog")}

    if not shutil.which("zenity"):
        return {"ok": False, "error": "zenity is needed to pick a file"}
    picked = subprocess.run(["zenity", "--file-selection", "--multiple", "--separator=\n",
                             "--title=Send to phone"], capture_output=True, text=True)
    files = [f for f in picked.stdout.splitlines() if f]
    if not files:
        return {"ok": False, "error": "cancelled"}
    ok = all(subprocess.run(["kdeconnect-cli", "-d", device_id, "--share", f],
                            capture_output=True, timeout=30).returncode == 0 for f in files)
    return {"ok": ok, "sent": len(files)}


def clipboard(backend, device_id):
    """Push this computer's clipboard to the phone, once.

    Continuous two-way sync is a setting of KDE Connect and GSConnect
    themselves; this is the one-off "send what I just copied".
    """
    if backend == "gsconnect":
        return {"ok": gsconnect_action(device_id, "clipboardPush")}
    ok = subprocess.run(["kdeconnect-cli", "-d", device_id, "--send-clipboard"],
                        capture_output=True, timeout=10).returncode == 0
    return {"ok": ok}


def first_reachable(listing):
    """(backend, id, name) of the first phone in reach, or None."""
    for device in listing.get("devices", []):
        if device.get("reachable") and listing.get("backend"):
            return listing["backend"], device["id"], device["name"]
    return None


ACTIONS = {"ring": ring, "send": send, "clipboard": clipboard}


def main(argv):
    command = argv[1] if len(argv) > 1 else "list"
    if command == "list":
        return list_devices()
    if command == "clipboard-first":
        target = first_reachable(list_devices())
        if not target:
            return {"ok": False, "error": "no phone in reach"}
        try:
            return dict(clipboard(target[0], target[1]), name=target[2])
        except (OSError, subprocess.SubprocessError) as error:
            return {"ok": False, "error": str(error)}
    if command in ACTIONS and len(argv) == 4:
        backend, device_id = argv[2], argv[3]
        if backend not in ("kdeconnect", "gsconnect") or not DEVICE_ID.match(device_id):
            return {"ok": False, "error": "bad device"}
        try:
            return ACTIONS[command](backend, device_id)
        except (OSError, subprocess.SubprocessError) as error:
            return {"ok": False, "error": str(error)}
    return {"ok": False, "error": f"unknown command {command}"}


def describe(result):
    """One line a person can read, for --notify."""
    if result.get("ok"):
        return f"Clipboard sent to {result['name']}" if result.get("name") else "Done"
    return {"no phone in reach": "No paired phone is in reach",
            "bad device": "That phone is not known"}.get(result.get("error"), "The phone did not take it")


if __name__ == "__main__":
    notify = "--notify" in sys.argv
    outcome = main([a for a in sys.argv if a != "--notify"])
    print(json.dumps(outcome))
    if notify:
        subprocess.run(["notify-send", "--app-name=Adaptive Command", "--icon=phone-symbolic",
                        "Phone", describe(outcome)], check=False)
