#!/usr/bin/env python3
"""Check Phone (apps/adaptive-phone) with stand-ins for adb and scrcpy: which
phone is chosen, finding it again on Wi-Fi, the phone's apps, what scrcpy is
asked to do, and the palette's phone mode. Nothing reaches a real phone."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parent.parent


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


phone = load(REPO / "apps/adaptive-phone/phone.py", "adaptive_phone")
sys.path.insert(0, str(REPO / "apps/adaptive-command"))
import modes  # noqa: E402

DEVICES = """List of devices attached
192.168.31.15:37601    device product:eqe_g model:motorola_edge_50_pro device:eqe transport_id:2
emulator-5584          device product:sdk_phone64_x86_64 model:Android_SDK_built_for_x86_64 device:emu64x transport_id:1
ZY22ABCD               unauthorized usb:1-2 transport_id:3
"""
found = phone.parse_devices(DEVICES)
assert [d["serial"] for d in found] == ["192.168.31.15:37601", "emulator-5584", "ZY22ABCD"], found
assert found[0]["model"] == "motorola edge 50 pro" and not found[0]["usb"] and found[2]["usb"]
# Never an emulator, never one that has not allowed this computer.
assert phone.pick(found)["serial"] == "192.168.31.15:37601"
assert phone.pick(phone.parse_devices("List of devices attached\nemulator-5584 device\n")) is None
# A cable before Wi-Fi; among equals, the one used last.
both = phone.parse_devices("ZY22ABCD device model:a\n10.0.0.2:5555 device model:b\n10.0.0.3:5555 device model:c\n")
assert phone.pick(both)["serial"] == "ZY22ABCD"
assert phone.pick(both[1:], "10.0.0.3:5555")["serial"] == "10.0.0.3:5555"

MDNS = """List of discovered mdns services
adb-ZY22ABCD-x1Yz	_adb-tls-pairing._tcp	192.168.31.15:41111
adb-ZY22ABCD-x1Yz	_adb-tls-connect._tcp	192.168.31.15:40005
"""
assert phone.parse_mdns(MDNS) == ["192.168.31.15:40005"]

LISTED = """[server] INFO: List of apps:
 * Settings                        com.android.settings
 - WhatsApp                        com.whatsapp
 - WhatsApp Business               com.whatsapp.w4b
 - Google Maps                     com.google.android.apps.maps
"""
apps = phone.parse_apps(LISTED)
assert [a["package"] for a in apps] == ["com.google.android.apps.maps", "com.whatsapp", "com.whatsapp.w4b",
                                        "com.android.settings"], apps
assert phone.find_app(apps, "whatsapp") == "com.whatsapp"            # the exact name first
assert phone.find_app(apps, "WhatsApp B") == "com.whatsapp.w4b"
assert phone.find_app(apps, "maps") == "com.google.android.apps.maps"
assert phone.find_app(apps, "com.example.notlisted") == "com.example.notlisted"
assert phone.find_app(apps, "nothing like it") == ""

whole = phone.scrcpy_argv("scrcpy", "S", "Phone")
assert ["--keyboard", "uhid"] == whole[whole.index("--keyboard"):whole.index("--keyboard") + 2]
assert "--keep-active" in whole and "--new-display" not in whole and "--turn-screen-off" not in whole
assert "--turn-screen-off" in phone.scrcpy_argv("scrcpy", "S", "Phone", screen_off=True)
one = phone.scrcpy_argv("scrcpy", "S", "WhatsApp", app="com.whatsapp")
for flag in ("--new-display", "--flex-display", "--no-vd-destroy-content", "--no-audio"):
    assert flag in one, (flag, one)
assert one[one.index("--start-app") + 1] == "com.whatsapp"

# The palette: the whole phone, then its apps, each opened through Phone.
cache = {"model": "motorola edge 50 pro", "apps": apps}
rows = modes.phone_rows("", cache)
assert rows[0]["title"] == "Phone" and rows[0]["action"] == ("run", [str(modes.PHONE)], None)
rows = modes.phone_rows("whats", cache)
assert [r["title"] for r in rows] == ["WhatsApp", "WhatsApp Business"], rows
assert rows[0]["action"] == ("run", [str(modes.PHONE), "app", "com.whatsapp"], None)
assert modes.phone_rows("", {})[-1]["title"] == "Phone apps are being fetched"
assert modes.mode_of("phone maps") == ("phone", "maps")

# The whole flow, with stand-ins: the phone's Wi-Fi port moved since it was
# last used, so it is found again on the network, then scrcpy is started.
with tempfile.TemporaryDirectory(prefix="adaptive-phone-") as temporary:
    root = Path(temporary)
    log = root / "log"
    (root / "adb").write_text(f"""#!/bin/sh
echo "adb $*" >> {log}
case "$1" in
  devices) if [ -f {root}/connected ]; then echo "List of devices attached"; echo "192.168.31.15:40005 device model:motorola_edge_50_pro"; else echo "List of devices attached"; fi ;;
  mdns) printf '%s\\n' "List of discovered mdns services" "adb-X	_adb-tls-connect._tcp	192.168.31.15:40005" ;;
  connect) if [ "$2" = 192.168.31.15:40005 ]; then touch {root}/connected; echo "connected to $2"; else echo "failed to connect to $2"; fi ;;
esac
""")
    (root / "scrcpy").write_text(f"""#!/bin/sh
echo "scrcpy ADB=$ADB $*" >> {log}
case "$*" in *--list-apps*) printf '%s\\n' "[server] INFO: List of apps:" " - WhatsApp                        com.whatsapp" ;; esac
""")
    for name in ("adb", "scrcpy"):
        (root / name).chmod(0o755)
    config = root / "config/adaptive-desktop/phone.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"serial": "192.168.31.15:37601", "address": "192.168.31.15:37601"}))
    env = dict(os.environ, ADAPTIVE_PHONE_ADB=str(root / "adb"), ADAPTIVE_PHONE_SCRCPY=str(root / "scrcpy"),
               XDG_CONFIG_HOME=str(root / "config"), XDG_CACHE_HOME=str(root / "cache"))
    script = str(REPO / "apps/adaptive-phone/phone.py")
    done = subprocess.run([sys.executable, script], env=env, capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    lines = log.read_text().splitlines()
    # The old port first, then the one the network offers.
    connects = [line for line in lines if line.startswith("adb connect")]
    assert connects == ["adb connect 192.168.31.15:37601", "adb connect 192.168.31.15:40005"], lines
    started = lines[-1]
    assert started.startswith(f"scrcpy ADB={root / 'adb'} --serial 192.168.31.15:40005 --window-title motorola edge 50 pro"), started
    assert json.loads(config.read_text())["address"] == "192.168.31.15:40005"

    log.write_text("")
    done = subprocess.run([sys.executable, script, "app", "whatsapp"], env=env, capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    lines = log.read_text().splitlines()
    assert any("--list-apps" in line for line in lines), lines
    assert "--start-app com.whatsapp" in lines[-1] and "--window-title WhatsApp - motorola edge 50 pro" in lines[-1], lines
    assert json.loads((root / "cache/adaptive-desktop/phone-apps.json").read_text())["apps"][0]["package"] == "com.whatsapp"

    done = subprocess.run([sys.executable, script, "app", "no such app"], env=env, capture_output=True, text=True, timeout=30)
    assert done.returncode == 1 and "No such phone app" in done.stderr, done

    # Locked. The password kept for this phone (by its serial number, not
    # its Wi-Fi address) unlocks it on standard input; the phone stays dark
    # while used from here and is locked again when the window closes.
    assert phone.parse_locked("    isKeyguardShowing=true\n") and not phone.parse_locked("isKeyguardShowing=false")
    assert phone.parse_awake("  mWakefulness=Awake") and not phone.parse_awake("  mWakefulness=Dozing")
    assert phone.typed("it's 12") == "'it'\\''s%s12'"
    (root / "adb").write_text(f"""#!/bin/sh
echo "adb $*" >> {log}
case "$1" in
  devices) echo "List of devices attached"; echo "192.168.31.15:40005 device model:motorola_edge_50_pro" ; exit ;;
esac
case "$3 $4" in
  "shell dumpsys") if [ "$5" = power ]; then echo "  mWakefulness=Awake"; elif [ -f {root}/unlocked ]; then echo "isKeyguardShowing=false"; else echo "isKeyguardShowing=true"; fi ;;
  "shell getprop") echo ZD2TEST ;;
  "shell input") echo "adb pressed $6" >> {log} ;;
  "shell ") script=$(cat); echo "script: $script" >> {log}; case "$script" in *"input text 'right%spass'"*) touch {root}/unlocked ;; esac ;;
esac
""")
    keys = root / "keyring.json"
    keys.write_text(json.dumps({"ZD2TEST": "right pass"}))
    env["ADAPTIVE_PHONE_KEYRING"] = str(keys)
    log.write_text("")
    done = subprocess.run([sys.executable, script], env=env, capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    lines = log.read_text().splitlines()
    assert not any("right" in line for line in lines if line.startswith(("adb ", "scrcpy "))), lines   # never in argv
    assert any(line.startswith("script: input keyevent KEYCODE_WAKEUP") for line in lines), lines
    started = next(line for line in lines if line.startswith("scrcpy "))
    assert "--turn-screen-off" in started, started
    assert lines[-1] == "adb pressed KEYCODE_POWER", lines

    # Refused: forgotten at once, never tried twice; the lock screen is shown
    # as it is, to be used from here.
    (root / "unlocked").unlink()
    keys.write_text(json.dumps({"ZD2TEST": "stale"}))
    log.write_text("")
    done = subprocess.run([sys.executable, script], env=env, capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    lines = log.read_text().splitlines()
    assert json.loads(keys.read_text()) == {}, keys.read_text()
    assert sum(line.startswith("script:") for line in lines) == 1, lines
    assert "--turn-screen-off" not in lines[-1] and "pressed" not in "".join(lines), lines
    assert "did not unlock" in done.stderr

print("PASS phone: phone choice, Wi-Fi rediscovery, apps, scrcpy arguments, palette mode, unlock and lock again")
