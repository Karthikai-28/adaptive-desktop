#!/usr/bin/env python3
"""Phone - the paired Android phone, used from this computer.

    adaptive-phone                 the whole phone in a window
    adaptive-phone --screen-off    the same, with the phone's own screen off
    adaptive-phone app NAME        one phone app in a window of its own
    adaptive-phone apps [--refresh]  the phone's apps (cached for the palette)
    adaptive-phone --forget-unlock the phone's password is no longer kept here

It is scrcpy (pinned in .local/scrcpy by scripts/install-phone.sh) over adb:
the phone's screen at full rate with its sound, a real touch for every click
and a hardware keyboard for typing, the clipboard both ways, and a file
dropped on the window goes to the phone's Download folder. An app opened on
its own gets a display of its own on the phone, sized to the window, so it
can be used here while the phone is used for something else; closing the
window hands the app back to the phone, as it was.

adb reaches the phone over USB or over Wi-Fi (Developer options, Wireless
debugging, paired once). The Wi-Fi port changes when the phone restarts; it
is found again by asking the network (mDNS). With no adb route at all, the
whole phone opens through Adaptive Link instead (phone_screen.py, which
Android asks about every time and which acts through accessibility).

A locked phone is used too. Android runs nothing past a secure lock screen
for anyone but itself, so Phone unlocks it as its owner would: with the
phone's PIN or password, asked once and kept in the login keyring (never in
a file, never on a command line). The phone's own screen stays dark while
it is used from here, and it is locked again when the last window closes.
One try per opening: a password the phone refuses is forgotten and asked
for again, so a stale one can never count towards Android's lockout. After
the phone restarts it has to be unlocked on the phone once (Android allows
no debugging before that).
"""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parent.parent.parent
SCRCPY_DIR = REPO / ".local/scrcpy"
SDK_ADB = REPO / ".local/android-sdk/platform-tools/adb"
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "adaptive-desktop/phone.json"
APPS_CACHE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "adaptive-desktop/phone-apps.json"
APPS_FRESH_S = 24 * 3600
_PACKAGE = re.compile(r"^[A-Za-z][\w]*(?:\.[\w]+)+$")
_APP_LINE = re.compile(r"^\s*([*-])\s+(.*?)\s+([A-Za-z][\w]*(?:\.[\w]+)+)\s*$")


def adb():
    """The adb that runs this computer's adb server (two versions would
    keep killing each other's): the repository SDK's, else the system's."""
    if os.environ.get("ADAPTIVE_PHONE_ADB"):
        return os.environ["ADAPTIVE_PHONE_ADB"]
    if SDK_ADB.exists():
        return str(SDK_ADB)
    return shutil.which("adb") or ""


def scrcpy():
    """The pinned scrcpy, or one on PATH."""
    if os.environ.get("ADAPTIVE_PHONE_SCRCPY"):
        return os.environ["ADAPTIVE_PHONE_SCRCPY"]
    pinned = SCRCPY_DIR / "scrcpy"
    return str(pinned) if pinned.exists() else shutil.which("scrcpy") or ""


def parse_devices(text):
    """`adb devices -l` as [{"serial", "state", "model", "usb"}]."""
    found = []
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) < 2 or line.startswith(("List of", "*")):
            continue
        fields = dict(p.split(":", 1) for p in parts[2:] if ":" in p)
        serial = parts[0]
        found.append({"serial": serial, "state": parts[1], "model": fields.get("model", "").replace("_", " "),
                      "usb": ":" not in serial and "._adb-tls-connect." not in serial and not serial.startswith("emulator-")})
    return found


def pick(devices, remembered=""):
    """The phone to use: never an emulator; a cable before Wi-Fi; the one
    used last before another."""
    ready = [d for d in devices if d["state"] == "device" and not d["serial"].startswith("emulator-")]
    ready.sort(key=lambda d: (not d["usb"], d["serial"] != remembered))
    return ready[0] if ready else None


def parse_mdns(text):
    """Addresses of phones offering Wireless debugging to this computer."""
    return [line.split()[-1] for line in (text or "").splitlines()
            if "_adb-tls-connect._tcp" in line and re.fullmatch(r"[\d.]+:\d+", line.split()[-1])]


def parse_apps(text):
    """`scrcpy --list-apps` as [{"name", "package", "system"}], by name."""
    apps = {}
    for line in (text or "").splitlines():
        line = re.sub(r"^\[server\]\s+\w+:\s*", "", line)
        match = _APP_LINE.match(line)
        if match:
            apps[match.group(3)] = {"name": match.group(2).strip(), "package": match.group(3), "system": match.group(1) == "*"}
    return sorted(apps.values(), key=lambda a: (a["system"], a["name"].casefold()))


def find_app(apps, wanted):
    """The package for a name: exact package, exact name, then a name that
    starts with it. "" when nothing matches."""
    if _PACKAGE.match(wanted) and any(a["package"] == wanted for a in apps):
        return wanted
    folded = wanted.casefold()
    for test in (lambda a: a["name"].casefold() == folded, lambda a: a["name"].casefold().startswith(folded),
                 lambda a: folded in a["name"].casefold()):
        hits = [a for a in apps if test(a)]
        if hits:
            return hits[0]["package"]
    return wanted if _PACKAGE.match(wanted) else ""


def scrcpy_argv(binary, serial, title, app="", screen_off=False):
    """What scrcpy is run with. The keyboard is a hardware one (uhid): every
    key reaches the app, shortcuts included, and the phone's on-screen
    keyboard stays out of the way. The phone is kept awake while a window is
    open (asleep, it would stop drawing), with its own screen dark if asked."""
    argv = [binary, "--serial", serial, "--window-title", title, "--keyboard", "uhid", "--keep-active"]
    if app:
        # A display of the phone's own for this app, resized with the window;
        # closing it moves the app back to the phone's screen, not away.
        argv += ["--new-display", "--flex-display", "--no-vd-destroy-content", "--start-app", app, "--no-audio"]
    if screen_off:
        argv += ["--turn-screen-off"]
    return argv


def parse_locked(dump):
    """Whether `dumpsys window` says the lock screen is up."""
    return bool(re.search(r"isKeyguardShowing=true|mDreamingLockscreen=true|\bmIsShowing=true", dump or ""))


def parse_awake(dump):
    """Whether `dumpsys power` says the phone is awake (not dozing or asleep)."""
    return "mWakefulness=Awake" in (dump or "")


def typed(secret):
    """The phone's `input text` argument for a password, quoted for its shell:
    a space is %s there."""
    return "'" + secret.replace("'", "'\\''").replace(" ", "%s") + "'"


def load(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.replace(path)


def run_adb(*args, timeout=10):
    try:
        done = subprocess.run([adb(), *args], capture_output=True, text=True, timeout=timeout)
        return done.stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def phone():
    """The phone to use, reconnecting over Wi-Fi when its port moved; None
    when there is no adb route to one."""
    if not adb():
        return None
    remembered = load(CONFIG)
    found = pick(parse_devices(run_adb("devices", "-l")), remembered.get("serial", ""))
    if found is None:
        tried = [remembered["address"]] if remembered.get("address") else []
        for address in tried + [a for a in parse_mdns(run_adb("mdns", "services")) if a not in tried]:
            if "connected" in run_adb("connect", address, timeout=8):
                time.sleep(.5)
                found = pick(parse_devices(run_adb("devices", "-l")), address)
                if found:
                    break
    if found:
        address = found["serial"] if re.fullmatch(r"[\d.]+:\d+", found["serial"]) else remembered.get("address", "")
        save(CONFIG, {"serial": found["serial"], "address": address, "model": found["model"]})
    return found


def tell(title, body):
    """Shown on the desktop when started from the app grid, printed otherwise."""
    print(f"{title}: {body}", file=sys.stderr)
    if not sys.stderr.isatty() and shutil.which("notify-send"):
        subprocess.run(["notify-send", "--app-name=Phone", "--icon=phone-symbolic", title, body], check=False)


def phone_apps(device, refresh=False):
    cached = load(APPS_CACHE)
    if not refresh and cached.get("apps") and time.time() - cached.get("time", 0) < APPS_FRESH_S:
        return cached["apps"]
    if not device or not scrcpy():
        return cached.get("apps", [])
    env = dict(os.environ, ADB=adb())
    try:
        done = subprocess.run([scrcpy(), "--serial", device["serial"], "--list-apps"], capture_output=True,
                              text=True, timeout=60, env=env)
        apps = parse_apps(done.stdout + "\n" + done.stderr)
    except (OSError, subprocess.TimeoutExpired):
        apps = []
    if apps:
        save(APPS_CACHE, {"time": time.time(), "model": device["model"], "apps": apps})
        return apps
    return cached.get("apps", [])


# ------------------------------------------------------------------ unlock

def keyring():
    """Where the phone's password is kept: the login keyring, or a file
    standing in for it in scripts/verify-phone.py."""
    test = os.environ.get("ADAPTIVE_PHONE_KEYRING")
    if test:
        path = Path(test)

        class File:
            get = staticmethod(lambda key: load(path).get(key, ""))
            put = staticmethod(lambda key, secret, label: save(path, {**load(path), key: secret}))
            drop = staticmethod(lambda key: save(path, {k: v for k, v in load(path).items() if k != key}))
        return File
    import gi
    gi.require_version("Secret", "1")
    from gi.repository import Secret
    schema = Secret.Schema.new("com.karthi.AdaptivePhone.Unlock", Secret.SchemaFlags.NONE,
                               {"phone": Secret.SchemaAttributeType.STRING})

    class Login:
        get = staticmethod(lambda key: Secret.password_lookup_sync(schema, {"phone": key}, None) or "")
        put = staticmethod(lambda key, secret, label: Secret.password_store_sync(
            schema, {"phone": key}, Secret.COLLECTION_DEFAULT, label, secret, None))
        drop = staticmethod(lambda key: Secret.password_clear_sync(schema, {"phone": key}, None))
    return Login


def shell(serial, script, timeout=15):
    """Commands for the phone's shell, given on standard input so that
    nothing in them shows in a process list here."""
    try:
        return subprocess.run([adb(), "-s", serial, "shell"], input=script, capture_output=True,
                              text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def phone_key(serial):
    """What the password is kept under: the phone's own serial number, which
    stays when its Wi-Fi address and port change."""
    return run_adb("-s", serial, "shell", "getprop", "ro.serialno").strip() or serial


def locked(serial):
    return parse_locked(run_adb("-s", serial, "shell", "dumpsys", "window"))


def ask_password(model):
    """The phone's PIN or password, typed by its owner here; "" if not."""
    if not shutil.which("zenity"):
        return ""
    try:
        done = subprocess.run(["zenity", "--entry", "--hide-text", "--title", f"Unlock {model}",
                               "--ok-label", "Unlock", "--width", "380", "--text",
                               f"{model} is locked. Its PIN or password unlocks it from here, now and next time.\n"
                               "It is kept in your login keyring, and the phone is locked again when you close it."],
                              capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout.rstrip("\n") if done.returncode == 0 else ""


def unlock(device):
    """Unlock a locked phone with its owner's password. True when it is
    unlocked (or was not locked); False leaves it as it was."""
    serial, model = device["serial"], device["model"] or "the phone"
    if not locked(serial):
        return True
    store, key = keyring(), phone_key(serial)
    secret = store.get(key)
    asked = not secret
    if asked:
        secret = ask_password(model)
        if not secret:
            return False
    # Awake, the lock screen's password field, the password, Enter.
    shell(serial, "input keyevent KEYCODE_WAKEUP\nsleep 0.4\nwm dismiss-keyguard\nsleep 0.8\n"
                  f"input text {typed(secret)}\ninput keyevent KEYCODE_ENTER\n")
    for _ in range(16):
        time.sleep(.25)
        if not locked(serial):
            if asked:
                store.put(key, secret, f"Phone unlock ({model})")
            return True
    # Refused: never tried again with the same password.
    store.drop(key)
    tell(f"{model} did not unlock", "The password was refused and is no longer kept here. "
         "Open Phone again to type it, or unlock the phone in your hand.")
    return False


def others(serial):
    """Other Phone windows still open on this phone."""
    try:
        out = subprocess.run(["pgrep", "-u", str(os.getuid()), "-a", "scrcpy"], capture_output=True, text=True).stdout
    except OSError:
        return False
    return any(f"--serial {serial} " in line + " " for line in out.splitlines())


def lock_again(serial):
    """The power button, as its owner would press it: Android locks at once."""
    if parse_awake(run_adb("-s", serial, "shell", "dumpsys", "power")):
        run_adb("-s", serial, "shell", "input", "keyevent", "KEYCODE_POWER")


def through_link():
    """The whole phone through Adaptive Link, where adb cannot reach it."""
    cli = REPO / "scripts/link-cli.py"
    done = subprocess.run([sys.executable, str(cli), "phone-screen"], capture_output=True, text=True, timeout=30)
    if done.returncode:
        tell("Phone is not reachable", "Turn on Wireless debugging on the phone (or plug it in), "
             "or open Adaptive Link on it.")
        return 1
    tell("Phone", "Allow the screen to be shown on the phone; Android asks every time.")
    return 0


def main(argv):
    args = list(argv)
    if args and args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    command = args.pop(0) if args and args[0] in ("app", "apps") else ""
    device = phone()
    if "--forget-unlock" in args:
        if device:
            keyring().drop(phone_key(device["serial"]))
        print("The phone's password is no longer kept here." if device else "No phone reachable over adb.")
        return 0 if device else 1
    if command == "apps":
        apps = phone_apps(device, refresh="--refresh" in args)
        if "--json" in args:
            print(json.dumps(apps))
        else:
            for app in apps:
                print(f"{app['name']:<32} {app['package']}")
        return 0 if apps else 1
    if device is None:
        if command == "app":
            tell("Phone is not reachable", "Phone apps open here over adb: turn on Wireless debugging on the phone, or plug it in.")
            return 1
        return through_link()
    if not scrcpy():
        tell("Phone needs scrcpy", "Run: ./install.sh --only phone")
        return 1
    model = device["model"] or "Phone"
    was_locked = locked(device["serial"])
    if was_locked and not unlock(device):
        was_locked = False   # still locked: shown as it is, its lock screen used from here
    if command == "app":
        wanted = " ".join(a for a in args if not a.startswith("--"))
        package = find_app(phone_apps(device), wanted) if wanted else ""
        if not package:
            tell("No such phone app", wanted or "Name an app: adaptive-phone app WhatsApp")
            return 1
        name = next((a["name"] for a in load(APPS_CACHE).get("apps", []) if a["package"] == package), package)
        argv = scrcpy_argv(scrcpy(), device["serial"], f"{name} - {model}", app=package, screen_off=was_locked)
    else:
        argv = scrcpy_argv(scrcpy(), device["serial"], model, screen_off=was_locked or "--screen-off" in args)
    if not was_locked:
        os.execvpe(argv[0], argv, dict(os.environ, ADB=adb()))
    # Unlocked for this: dark while used from here, locked once the last
    # window on it closes.
    code = subprocess.run(argv, env=dict(os.environ, ADB=adb())).returncode
    if not others(device["serial"]):
        lock_again(device["serial"])
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
