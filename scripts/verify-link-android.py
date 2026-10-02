#!/usr/bin/env python3
"""Adaptive Link on Android, for real: an emulator, the app's own client and
this device's keystore, against the real daemon.

verify-link.py plays the phone in Python. This runs the Android code itself:
it starts the daemon in a sandbox, opens pairing, and runs the app's
instrumented test on a running emulator (or a connected phone), pressing
"Pair" on the computer's side when the phone asks.

    scripts/verify-link-android.py

Skips if no Android device is attached to adb or the SDK is not installed.
Start the emulator with: scripts/link-emulator.sh
"""

import base64
import json
import os
import shutil
import site
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SDK = REPO / ".local" / "android-sdk"
APP = REPO / "apps" / "adaptive-link-android"
LINK = REPO / "services" / "adaptive-link"
PORT, PAIRING_PORT = 47933, 47934
# How an Android emulator reaches the machine it runs on.
EMULATOR_HOST = "10.0.2.2"


def gradle():
    found = sorted(Path.home().glob(".gradle/wrapper/dists/gradle-8.13-bin/*/gradle-8.13/bin/gradle"))
    return str(found[0]) if found else shutil.which("gradle")


def stop_sandbox(daemon, sandbox):
    """Stop everything started for this run.

    dbus-run-session starts the daemon in a session of its own, so signalling
    the wrapper's process group does not reach it. Every process of this run
    carries the sandbox path in its environment; that is what is looked for.
    """
    import signal
    marker = str(sandbox).encode()
    for entry in os.listdir("/proc"):
        if not entry.isdigit() or int(entry) == os.getpid():
            continue
        try:
            with open(f"/proc/{entry}/environ", "rb") as handle:
                if marker in handle.read():
                    os.kill(int(entry), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            continue
    try:
        os.killpg(daemon.pid, signal.SIGTERM)
        daemon.wait(timeout=10)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        pass
    # The sandbox session mounts a gvfs folder in its runtime directory,
    # which has to be unmounted before the directory can be removed.
    subprocess.run(["fusermount", "-uz", str(Path(sandbox) / "run" / "gvfs")],
                   capture_output=True, check=False)


def _offer(control, device):
    offer = json.loads(control.call("POST", "/pair/start")["payload"])
    if device.startswith("emulator-"):
        offer["h"] = [EMULATOR_HOST]
    return base64.urlsafe_b64encode(json.dumps(offer).encode()).decode()


def screens(check, adb, device, control, build_env, offer_for):
    """Open the app itself, paired, and visit every screen.

    The app is installed and paired through its own test (which, unlike
    Gradle's connected test, leaves it installed), then started and driven
    with taps. Each screen is read back as text through the accessibility
    tree, and the device log is checked for a crash.
    """
    import re
    import xml.etree.ElementTree as ET

    def sh(*args, timeout=60):
        return subprocess.run([str(adb), "-s", device, *args], capture_output=True, text=True, timeout=timeout).stdout

    built = subprocess.run([gradle(), "--no-daemon", "-q", "assembleDebug", "assembleDebugAndroidTest"],
                           cwd=APP, env=build_env, capture_output=True, text=True, timeout=1500)
    if built.returncode != 0:
        check(False, "the app and its test build")
        print(built.stderr[-2000:])
        return
    sh("install", "-r", "-g", str(APP / "app/build/outputs/apk/debug/app-debug.apk"), timeout=180)
    sh("install", "-r", str(APP / "app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk"), timeout=180)

    def owner():
        for _ in range(240):
            if control.call("GET", "/pair/state").get("state") == "pending":
                control.call("POST", "/pair/decide", {"accept": True})
                return
            time.sleep(0.5)

    threading.Thread(target=owner, daemon=True).start()
    result = sh("shell", "am", "instrument", "-w", "-e", "offer", offer_for(), "-e", "stay", "1",
                "com.karthi.adaptivelink.test/androidx.test.runner.AndroidJUnitRunner", timeout=240)
    check("OK (1 test)" in result, "the app is left paired on the device")
    if "OK (1 test)" not in result:
        print(result[-1500:])
        return

    def texts():
        """Every piece of text on the screen, and where to tap for it."""
        sh("shell", "uiautomator", "dump", "/sdcard/ui.xml")
        raw = sh("shell", "cat", "/sdcard/ui.xml")
        found = {}
        try:
            for node in ET.fromstring(raw[raw.index("<?xml"):]).iter("node"):
                label = node.get("text") or node.get("content-desc")
                box = re.findall(r"\d+", node.get("bounds", ""))
                if label and len(box) == 4:
                    found[label] = ((int(box[0]) + int(box[2])) // 2, (int(box[1]) + int(box[3])) // 2)
        except (ValueError, ET.ParseError):
            pass
        return found

    def tap(label, wait=2.0):
        where = texts().get(label)
        if not where:
            return False
        sh("shell", "input", "tap", str(where[0]), str(where[1]))
        time.sleep(wait)
        return True

    def has(*wanted):
        seen = texts()
        return all(any(w in label for label in seen) for w in wanted)

    sh("logcat", "-c")
    sh("shell", "am", "start", "-n", "com.karthi.adaptivelink/.MainActivity")
    for _ in range(30):
        if has("Connected"):
            break
        time.sleep(1)
    check(has("Connected", "Screen", "Trackpad", "Presenter", "Webcam"), "home: connected, with its tiles")

    visits = [
        ("Screen", ("Screen",), "screen: opens"),
        ("Trackpad", ("Drag to move",), "trackpad: opens"),
        ("Media", ("Nothing is playing",), "media: says nothing is playing"),
        ("Presenter", ("Next", "Previous", "Start timer"), "presenter: opens with its timer"),
        ("Run", ("Output appears here",), "run: opens"),
        ("Files", ("Downloads",), "files: lists the computer's home folder"),
        ("More", ("Clipboard", "Get from computer", "Unpair this phone"), "more: clipboard, power and security"),
    ]
    for tile, expected, message in visits:
        opened = tap(tile)
        check(opened and has(*expected), message)
        sh("shell", "input", "keyevent", "KEYCODE_BACK")
        time.sleep(1.2)

    # Run a command from the phone's own screen.
    if tap("Run"):
        where = texts().get("A command to run on the computer")
        if where:
            sh("shell", "input", "tap", str(where[0]), str(where[1]))
            time.sleep(1)
            sh("shell", "input", "text", "echo%sscreen-check")
            sh("shell", "input", "keyevent", "KEYCODE_ENTER")
            time.sleep(4)
        check(has("screen-check", "finished: 0"), "run: a command typed on the phone runs and its output is shown")
        sh("shell", "input", "keyevent", "KEYCODE_BACK")
        sh("shell", "input", "keyevent", "KEYCODE_BACK")

    crashes = sh("logcat", "-d", "-s", "AndroidRuntime:E")
    check("FATAL EXCEPTION" not in crashes, "the app did not crash on any screen")
    if "FATAL EXCEPTION" in crashes:
        print(crashes[-3000:])
    sh("shell", "am", "force-stop", "com.karthi.adaptivelink")


def main():
    adb = SDK / "platform-tools" / "adb"
    if not adb.exists() or not gradle():
        print("SKIP Android link: the Android SDK or Gradle is not installed")
        return 0
    devices = [line.split()[0] for line in subprocess.run(
        [str(adb), "devices"], capture_output=True, text=True).stdout.splitlines()[1:] if line.endswith("\tdevice")]
    if not devices:
        print("SKIP Android link: no emulator or phone is attached (scripts/link-emulator.sh)")
        return 0

    failures = []

    def check(ok, message):
        print(f"{'OK  ' if ok else 'FAIL'} {message}")
        if not ok:
            failures.append(message)

    sandbox = Path(tempfile.mkdtemp(prefix="adaptive-link-android."))
    (sandbox / "run").mkdir(mode=0o700)
    (sandbox / "home" / "Downloads").mkdir(parents=True)
    (sandbox / "home" / "Downloads" / "movie.mkv").write_bytes(b"x" * 2048)
    env = dict(os.environ, HOME=str(sandbox / "home"), XDG_RUNTIME_DIR=str(sandbox / "run"),
               ADAPTIVE_LINK_PORT=str(PORT), ADAPTIVE_LINK_PAIRING_PORT=str(PAIRING_PORT),
               PYTHONPATH=site.getusersitepackages())
    env.pop("DBUS_SESSION_BUS_ADDRESS", None)
    daemon = subprocess.Popen(
        ["xvfb-run", "-a", "-s", "-screen 0 1280x800x24", "dbus-run-session", "--",
         sys.executable, str(LINK / "server.py")],
        env=env, stdout=open(sandbox / "daemon.log", "w"), stderr=subprocess.STDOUT,
        # Its own process group: stopping it has to reach the daemon inside
        # xvfb-run and dbus-run-session, not just the outermost wrapper.
        start_new_session=True)

    os.environ["XDG_RUNTIME_DIR"] = str(sandbox / "run")
    sys.path.insert(0, str(LINK))
    import control
    try:
        for _ in range(100):
            try:
                control.status()
                break
            except control.NotRunning:
                time.sleep(0.2)
        offer = json.loads(control.call("POST", "/pair/start")["payload"])
        offer["h"] = [EMULATOR_HOST] if devices[0].startswith("emulator-") else offer["h"]
        encoded = base64.urlsafe_b64encode(json.dumps(offer).encode()).decode()

        # The owner's part: when the phone asks, compare and press Pair.
        seen = {}

        def owner():
            for _ in range(600):
                state = control.call("GET", "/pair/state")
                if state.get("state") == "pending":
                    seen.update(state)
                    control.call("POST", "/pair/decide", {"accept": True})
                    return
                time.sleep(0.5)

        threading.Thread(target=owner, daemon=True).start()

        build_env = dict(os.environ, ANDROID_HOME=str(SDK), ANDROID_SERIAL=devices[0])
        build_env["XDG_RUNTIME_DIR"] = f"/run/user/{os.getuid()}"
        done = subprocess.run(
            [gradle(), "--no-daemon", "-q", "connectedDebugAndroidTest",
             f"-Pandroid.testInstrumentationRunnerArguments.offer={encoded}"],
            cwd=APP, env=build_env, capture_output=True, text=True, timeout=1500)

        check(seen.get("name") == "Test Phone", f"the phone asked to pair, by name ({seen.get('name')})")
        check(done.returncode == 0, "the app paired with its keystore key, connected over mutual TLS, "
              "received the screen, ran a command, and refused an impostor - on Android")
        if done.returncode != 0:
            print((done.stdout + done.stderr)[-3000:])
        state = control.status()
        check(state["phone"] is not None and state["phone"]["name"] == "Test Phone", "the computer holds the phone's certificate")
        log = control.call("GET", "/log")["entries"]
        actions = [entry["action"] for entry in log]
        check("exec" in actions and "screen" in actions, "the computer's audit log shows what the phone did")
        check(daemon.poll() is None, "the daemon stayed up throughout")

        screens(check, adb, devices[0], control, build_env, offer_for=lambda: _offer(control, devices[0]))
        text = (sandbox / "daemon.log").read_text()
        check("Traceback" not in text, "no exceptions in the daemon's log")
        if "Traceback" in text:
            print(text[-2500:])
    finally:
        stop_sandbox(daemon, sandbox)
        shutil.rmtree(sandbox, ignore_errors=True)

    print()
    print(f"{len(failures)} check(s) failed" if failures else "Android link checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
