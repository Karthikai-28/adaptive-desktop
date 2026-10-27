#!/usr/bin/env python3
"""Phone - the paired Android phone, used from this computer.

    adaptive-phone                 the whole phone in a window
    adaptive-phone --screen-off    the same, with the phone's own screen off
    adaptive-phone app NAME        one phone app in a window of its own
    adaptive-phone apps [--refresh]  the phone's apps (cached for the palette)
    adaptive-phone --forget-unlock the phone's password is no longer kept here
    adaptive-phone get             choose recent files on the phone; they are copied here
    adaptive-phone get PATH... [--open]   these, into ~/Downloads/Phone
    adaptive-phone files TEXT      files on the phone whose names have TEXT in them

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

Files go both ways: one dropped on the window goes to the phone's Download
folder (scrcpy), and `get` brings the phone's to ~/Downloads/Phone - where
the phone's own Share, *Send to computer*, puts them through Adaptive Link -
without touching the phone.

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
RECEIVED = Path.home() / "Downloads" / "Phone"
STORAGE = "/sdcard"
# Where a phone keeps what its owner made or was sent: the first look.
RECENT_FOLDERS = ("Download", "DCIM", "Pictures", "Documents", "Recordings", "Movies", "Music")
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


def quote(text):
    """A word for the phone's shell, whatever is in it."""
    return "'" + text.replace("'", "'\\''") + "'"


def parse_listing(text):
    """Lines of "mtime|size|path" (stat on the phone) as files, newest first."""
    files = []
    for line in (text or "").splitlines():
        stamp, _, rest = line.partition("|")
        size, _, path = rest.partition("|")
        if stamp.isdigit() and size.isdigit() and path.startswith("/"):
            files.append({"path": path, "name": path.rsplit("/", 1)[-1], "folder": path.rsplit("/", 1)[0],
                          "size": int(size), "time": int(stamp)})
    return sorted(files, key=lambda f: -f["time"])


def shown(folder):
    """A phone folder as its owner knows it: Download, DCIM/Camera."""
    for root in ("/storage/emulated/0", STORAGE):
        if folder == root or folder.startswith(root + "/"):
            return folder[len(root) + 1:] or "Internal storage"
    return folder


def size_text(size):
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


def received_as(name, folder=None):
    """Where a file from the phone lands: its own name, numbered if taken."""
    folder = folder or RECEIVED
    target = folder / name
    stem, suffix = target.stem, target.suffix
    number = 1
    while target.exists():
        number += 1
        target = folder / f"{stem} ({number}){suffix}"
    return target


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


# ------------------------------------------------------------------- files

# Hidden files and apps' private storage are never offered.
_LIST = "2>/dev/null | head -{limit} | tr '\\n' '\\0' | xargs -0 stat -c '%Y|%s|%n' 2>/dev/null"


def recent_files(serial, days=30, limit=300):
    """What changed on the phone lately, in the folders its owner uses."""
    folders = " ".join(quote(f"{STORAGE}/{f}") for f in RECENT_FOLDERS)
    return parse_listing(shell(serial, f"find {folders} -type f ! -path '*/.*' -mtime -{int(days)} "
                                       + _LIST.format(limit=limit) + "\n", timeout=30))


def parse_media(text):
    """`content query` rows of the phone's media index as files, newest first."""
    lines = []
    for line in (text or "").splitlines():
        match = re.match(r"^Row: \d+ _data=(/.*), _size=(\d+|NULL), date_modified=(\d+|NULL)$", line)
        if match:
            size, stamp = (v if v.isdigit() else "0" for v in (match.group(2), match.group(3)))
            lines.append(f"{stamp}|{size}|{match.group(1)}")
    return parse_listing("\n".join(lines))


def search_files(serial, text, limit=40):
    """Files anywhere in the phone's shared storage whose names have this in
    them. Android's own index answers in a second or so; walking the storage
    takes ten, and is what is done only where the index cannot be asked."""
    word = text.strip()
    if len(word) < 2:
        return []
    like = word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").replace("'", "''")
    where = (f"_display_name LIKE '%{like}%' ESCAPE '\\' AND _data NOT LIKE '%/.%' "
             "AND _data NOT LIKE '/storage/emulated/0/Android/%' AND _size > 0")
    out = shell(serial, "content query --uri content://media/external/file --projection _data:_size:date_modified "
                        f"--where {quote(where)} --sort {quote('date_modified DESC')}\n", timeout=30)
    if "Row:" in out or "No result found" in out:
        return parse_media(out)[:limit]
    glob = re.sub(r"[*?\[\]\\]", "", word)
    # Pruned, not filtered: apps' storage and hidden folders are never walked.
    return parse_listing(shell(serial, f"find {STORAGE}/ \\( -path {STORAGE}/Android -o -name '.*' \\) -prune -o "
                                       f"-type f -iname {quote('*' + glob + '*')} -print " + _LIST.format(limit=limit) + "\n",
                               timeout=30))


def pull(serial, paths, folder=None):
    """Copy files from the phone here; what arrived, in order."""
    folder = folder or RECEIVED
    folder.mkdir(parents=True, exist_ok=True)
    arrived = []
    for path in paths:
        if not path.startswith("/"):
            path = f"{STORAGE}/{path}"
        target = received_as(path.rsplit("/", 1)[-1], folder)
        try:
            done = subprocess.run([adb(), "-s", serial, "pull", "-a", path, str(target)], capture_output=True,
                                  text=True, timeout=3600)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if done.returncode == 0 and target.exists():
            arrived.append(target)
    return arrived


def choose(files):
    """The files its owner ticks in a list of the phone's recent ones."""
    if not files or not shutil.which("zenity"):
        return []
    rows = []
    for f in files:
        rows += ["FALSE", f["name"], shown(f["folder"]), size_text(f["size"]),
                 time.strftime("%d %b %H:%M", time.localtime(f["time"])), f["path"]]
    try:
        done = subprocess.run(["zenity", "--list", "--checklist", "--title", "Get files from the phone",
                               "--text", "Recent files on the phone, newest first. Ticked ones are copied to Downloads/Phone.",
                               "--width", "760", "--height", "560", "--ok-label", "Copy here",
                               "--column", "", "--column", "Name", "--column", "Folder", "--column", "Size",
                               "--column", "Changed", "--column", "Path", "--hide-column", "6",
                               "--print-column", "6", "--separator", "\n", *rows],
                              capture_output=True, text=True, timeout=3600)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [line for line in done.stdout.splitlines() if line.startswith("/")] if done.returncode == 0 else []


def open_path(path):
    if shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)


def get(device, paths, open_it=False):
    """Bring files from the phone; with none named, its owner picks them."""
    serial = device["serial"]
    if not paths:
        files = recent_files(serial)
        if not files:
            tell("Nothing new on the phone", "No files changed in the last 30 days in its usual folders. "
                 "Search all of it with \"phone files NAME\" in the palette.")
            return 1
        paths = choose(files)
        if not paths:
            return 0
        open_it = False
    arrived = pull(serial, paths)
    if not arrived:
        tell("Nothing was copied", "The phone did not give the file(s); is it still connected?")
        return 1
    named = arrived[0].name if len(arrived) == 1 else f"{len(arrived)} files"
    tell("From the phone", f"{named} in Downloads/Phone")
    open_path(arrived[0] if open_it and len(arrived) == 1 else RECEIVED)
    return 0 if len(arrived) == len(paths) else 1


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
    command = args.pop(0) if args and args[0] in ("app", "apps", "get", "files") else ""
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
    if command in ("get", "files") and device is None:
        tell("Phone is not reachable", "Files come over adb: turn on Wireless debugging on the phone, or plug it in. "
             "On the phone, Share - Send to computer works through Adaptive Link.")
        return 1
    if command == "get":
        return get(device, [a for a in args if not a.startswith("--")], open_it="--open" in args)
    if command == "files":
        found = search_files(device["serial"], " ".join(a for a in args if not a.startswith("--")))
        if "--json" in args:
            print(json.dumps(found))
        for f in [] if "--json" in args else found:
            print(f"{f['path']}  ({size_text(f['size'])})")
        return 0 if found else 1
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
