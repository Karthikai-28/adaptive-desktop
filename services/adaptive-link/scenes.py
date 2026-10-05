"""Adaptive Link - knowing where the computer is, and what you do there.

`context` is the situation in a few plain facts: which network, how many
displays, on mains or battery, whether the phone is here, which project. It
is what everything that anticipates reads, so that none of it works the
situation out again for itself.

A *scene* is a situation that comes round again - at the desk, away,
presenting - with what you always do in it: the sound output, the power
profile, focus, the brightness, the appearance. Scenes are not guessed. You
arrange things the way you like them and save that as a scene; from then on,
whenever the situation is the same, it is offered - or simply applied, for a
scene you have said to apply without asking.

`doctor` is the other half of needing no one: the link looking at itself,
and saying for each thing that is wrong the one thing that puts it right.
"""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import desktop
import machine
import system

FACTS = ("wifi", "displays", "power", "phone")


def context(phone_here=False):
    """The situation now."""
    network = system.network()
    wifi = next((entry["wifi"]["name"] for entry in network["interfaces"] if entry.get("wifi")), "")
    battery = machine.battery()
    return {
        "wifi": wifi,
        "displays": sum(1 for output in machine.display()["outputs"] if output["on"]),
        "power": "battery" if battery and not battery["charging"] else "mains",
        "phone": bool(phone_here),
        "project": next((project["name"] for project in system.projects() if project["active"]), ""),
    }


def arrangement():
    """How things are set now, as the actions that would set them so again
    (actions.py). What a scene is made of."""
    steps = []
    output = next((device for device in machine.sound()["outputs"] if device["default"]), None)
    if output:
        steps.append({"id": "sound-output", "args": {"device": output["name"], "name": output["label"]}})
    well = machine.health()
    if well["profile"]:
        steps.append({"id": "profile", "args": {"profile": well["profile"]}})
    state = system.desktop_state()
    steps.append({"id": "focus", "args": {"state": "on" if state["focus"] else "off"}})
    steps.append({"id": "dark" if state["dark"] else "light", "args": {}})
    brightness = machine.display()["brightness"]
    if brightness:
        steps.append({"id": "brightness", "args": {"to": brightness}})
    return steps


def fits(scene, now):
    """Whether the situation is the scene's: every fact the scene names is so."""
    when = scene.get("when") or {}
    return bool(when) and all(now.get(key) == value for key, value in when.items())


class Scenes:
    def __init__(self, link_dir):
        self._path = Path(link_dir) / "scenes.json"
        self.scenes = self._load()
        self.active = set()   # the scenes the situation fitted when last looked at

    def _load(self):
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [scene for scene in data if isinstance(scene, dict) and isinstance(scene.get("name"), str)
                and isinstance(scene.get("when"), dict) and isinstance(scene.get("do"), list)] if isinstance(data, list) else []

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self.scenes, indent=2) + "\n", encoding="utf-8")

    def save(self, name, now, steps, auto=False, facts=FACTS):
        """Keep how things are as the scene for the situation as it is."""
        name = " ".join(str(name or "").split())[:40]
        if not name:
            return None
        scene = {"name": name, "when": {key: now[key] for key in facts if key in now}, "do": steps, "auto": bool(auto)}
        self.scenes = [other for other in self.scenes if other["name"] != name] + [scene]
        self._save()
        return scene

    def forget(self, name):
        kept = [scene for scene in self.scenes if scene["name"] != name]
        if len(kept) == len(self.scenes):
            return False
        self.scenes = kept
        self._save()
        return True

    def find(self, name):
        return next((scene for scene in self.scenes if scene["name"] == name), None)

    def entered(self, now):
        """The scenes the situation has just come to fit: those that fit now
        and did not when last looked at."""
        fitting = {scene["name"] for scene in self.scenes if fits(scene, now)}
        new = [scene for scene in self.scenes if scene["name"] in fitting - self.active]
        self.active = fitting
        return new


# ------------------------------------------------------------------- doctor

def _has(tool):
    return shutil.which(tool) is not None


def _module(name):
    try:
        __import__(name)
        return True
    except Exception:  # noqa: BLE001 - whatever stops it loading, it is not there to use
        return False


def doctor(status):
    """The link looking at itself: [{"name", "ok", "text", "fix"}], with the
    things that matter most first. `status` is the daemon's own description
    (Link.describe); the rest is looked at here."""
    checks = []

    def check(name, ok, text, fix=""):
        checks.append({"name": name, "ok": bool(ok), "text": text, "fix": "" if ok else fix})

    check("The link", status["enabled"] and not status["problem"],
          "on" if status["enabled"] and not status["problem"] else status["problem"] or "turned off",
          "scripts/link-cli.py on" if not status["enabled"] else "another program has the port: stop it, or change the port in config.json")
    check("A phone", bool(status["phones"]), f"{len(status['phones'])} paired" if status["phones"] else "none paired",
          "scripts/link-cli.py pair")
    check("Listening", status["listening"] or not status["phones"], f"port {status['port']}" if status["listening"] else "not listening",
          "systemctl --user restart adaptive-link")
    check("The account", status["cloud"] in ("connected", "not set up"),
          {"connected": f"signed in as {status['account']}", "not set up": "not set up (pairing by code, on this network only)"}.get(
              status["cloud"], status["cloud"]),
          "scripts/link-cli.py signin")
    for tool, what, package in (("xdotool", "pointer and keyboard", "xdotool"), ("xclip", "the clipboard", "xclip"),
                                ("nmcli", "the network", "network-manager"), ("udisksctl", "drives", "udisks2"),
                                ("bluetoothctl", "Bluetooth", "bluez"), ("pactl", "sound", "pulseaudio-utils"),
                                ("xrandr", "displays", "x11-xserver-utils"), ("dbus-monitor", "notifications to the phone", "dbus")):
        check(f"{what[0].upper()}{what[1:]}", _has(tool), "ready" if _has(tool) else f"{tool} is not installed", f"sudo apt install {package}")
    import importlib.util
    pydeps = Path(__file__).resolve().parent.parent.parent / ".local" / "link-pydeps"
    video = (pydeps / "aiortc").is_dir() or importlib.util.find_spec("aiortc") is not None
    check("Video, sound and away", video, "ready" if video else "aiortc is not installed",
          "pip install --target .local/link-pydeps aiortc")
    import camera
    check("Phone as webcam", camera.find_device() is not None, camera.find_device() or "the virtual camera is not installed",
          "scripts/install-link-camera.sh")
    import virtual_display
    room = virtual_display.capacity()
    check("Phone as another display", room > 0, (f"ready, for {room} device{'s' if room != 1 else ''} at once" if room
                                                 else "no display to spare"), "scripts/install-link-display.sh")
    import pen
    check("Phone's pen as a tablet", True, "ready" if pen.available() else
          "not installed (optional, the pen is a pointer until then: scripts/install-link-pen.sh)")
    import usb_link
    check("Over a USB cable", True, "ready" if usb_link.adb() else "adb is not installed (optional: sudo apt install adb)")
    usb = system.usb_devices()
    check("USB switching", not usb or any(device["switchable"] for device in usb),
          "ready" if any(device["switchable"] for device in usb) else "the switches are still the system's",
          "scripts/install-link-usb.sh")
    sudo = Path("/usr/local/lib/adaptive-link/link-approve").exists()
    check("sudo by the phone", True, "installed" if sudo else "not installed (optional: scripts/install-link-sudo.sh)")
    try:
        waking = system.wake_state()
        check("Waking the computer", True, "on" if waking["on"] else "off (optional: scripts/link-cli.py wake on)")
    except Exception:  # noqa: BLE001 - not being able to ask is itself the answer
        pass
    # A certificate that is about to lapse would lock every phone out at once.
    try:
        from cryptography import x509
        import identity
        cert = x509.load_pem_x509_certificate((Path(identity.LINK_DIR) / "server.crt").read_bytes())
        left = (getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after.replace(
            tzinfo=__import__("datetime").timezone.utc)).timestamp() - time.time()
        check("The computer's certificate", left > 30 * 86400, f"good for {int(left // 86400)} days",
              "delete ~/.config/adaptive-desktop/link/server.* and pair again")
    except (OSError, ValueError):
        pass
    checks.sort(key=lambda item: item["ok"])
    return checks
