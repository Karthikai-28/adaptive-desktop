#!/usr/bin/env python3
"""Adaptive Link on Android, for real: an emulator, the app's own client and
this device's keystore, against the real daemon and a stand-in for Google.

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
PORT, PAIRING_PORT, CLOUD_PORT = 47933, 47934, 47953
PIN = "2580"
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


ABIS = "-Pabi=arm64-v8a,x86_64"   # the app is built for phones; the emulator is x86_64


def stand_in(email="me@example.com"):
    """What tells the app where the stand-in for Google is, as the emulator sees it."""
    base = f"http://{EMULATOR_HOST}:{CLOUD_PORT}"
    return base64.urlsafe_b64encode(json.dumps({
        "api_key": "test-key", "database_url": base, "web_client_id": "web-client",
        "sign_in": f"{base}/signin", "refresh": f"{base}/refresh",
        "test_identity": f"google:{email}", "stun": ""}).encode()).decode()


# How long the daemon waits for the phone to keep a change to the network.
KEEP_S = 12


def screens(check, adb, device, control, build_env, sandbox):
    """Use the app itself, the way its owner does: every button.

    The app is installed fresh, paired through its own pairing screen (with
    the code typed, since an emulator cannot be shown a QR code), and then
    every screen is opened and every control on it pressed. Each screen is
    read back as text through the accessibility tree, and the device log is
    checked for a crash after every step - the first version of this check
    opened the screens and pressed nothing, and missed a crash on the very
    first button.
    """
    import re
    import xml.etree.ElementTree as ET

    def sh(*args, timeout=60):
        return subprocess.run([str(adb), "-s", device, *args], capture_output=True, text=True, timeout=timeout).stdout

    built = subprocess.run([gradle(), "--no-daemon", "-q", "assembleDebug", "assembleDebugAndroidTest", ABIS],
                           cwd=APP, env=build_env, capture_output=True, text=True, timeout=1500)
    if built.returncode != 0:
        check(False, "the app builds")
        print(built.stderr[-2000:])
        return
    sh("uninstall", "com.karthi.adaptivelink")
    # Installed as a person installs it: no permissions granted in advance.
    sh("install", "-r", str(APP / "app/build/outputs/apk/debug/app-debug.apk"), timeout=180)
    on_emulator = device.startswith("emulator-")
    if on_emulator:
        # Beside it, the test's own package: it is what tells the app to use
        # the stand-in for Google. Nothing outside the app can tell it that.
        sh("install", "-r", "-t", str(APP / "app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk"), timeout=180)

    def signed_in_as(email):
        """Whose Google account the phone's account picker will hand the app."""
        sh("shell", "am", "instrument", "-w", "-e", "class",
           "com.karthi.adaptivelink.LinkInstrumentedTest#pointAtStandIn",
           "-e", "cloud", stand_in(email), "com.karthi.adaptivelink.test/androidx.test.runner.AndroidJUnitRunner")

    def nodes():
        """[(label, x, y)] for every piece of text or described control on screen."""
        sh("shell", "uiautomator", "dump", "/sdcard/ui.xml")
        raw = sh("shell", "cat", "/sdcard/ui.xml")
        found = []
        try:
            for node in ET.fromstring(raw[raw.index("<?xml"):]).iter("node"):
                box = re.findall(r"\d+", node.get("bounds", ""))
                if len(box) != 4:
                    continue
                centre = ((int(box[0]) + int(box[2])) // 2, (int(box[1]) + int(box[3])) // 2)
                for label in (node.get("text"), node.get("content-desc")):
                    if label:
                        found.append((label, *centre))
        except (ValueError, ET.ParseError):
            pass
        return found

    def has(*wanted):
        labels = [label for label, _x, _y in nodes()]
        return all(any(w in label for label in labels) for w in wanted)

    def tap(label, wait=1.5, exact=True):
        for found, x, y in nodes():
            # Android's own dialogs spell their buttons differently between
            # versions ("While using the app", "WHILE USING THE APP").
            if found.casefold() == label.casefold() or (not exact and label.casefold() in found.casefold()):
                sh("shell", "input", "tap", str(x), str(y))
                time.sleep(wait)
                return True
        return False

    def reach(label):
        """Scroll down until `label` is on screen."""
        for _ in range(6):
            if has(label):
                return True
            sh("shell", "input", "swipe", "540", "1700", "540", "900", "300")
            time.sleep(1)
        return has(label)

    def back(wait=1.2):
        sh("shell", "input", "keyevent", "KEYCODE_BACK")
        time.sleep(wait)

    def focused():
        return sh("shell", "dumpsys", "window", "displays").split("mCurrentFocus=")[-1].split("\n")[0]

    def crashed():
        # The app's own crashes only: the test tools log theirs in the same place.
        return "Process: com.karthi.adaptivelink" in sh("logcat", "-d", "-s", "AndroidRuntime:E")

    def step(ok, message):
        """A check that also fails if the app has crashed since the last one."""
        dead = crashed()
        check(ok and not dead, message + (" - THE APP CRASHED" if dead else ""))
        if not ok and not dead:
            # What was on screen instead, to make the failure readable.
            print("     on screen:", [label[:28] for label, _x, _y in nodes()][:14], "| focus:", focused().strip()[-50:])
        if dead:
            print(sh("logcat", "-d", "-s", "AndroidRuntime:E")[-2500:])
            sh("logcat", "-c")
            sh("shell", "am", "start", "-n", "com.karthi.adaptivelink/.MainActivity")
            time.sleep(3)

    def home():
        """Back to the app's home screen, from wherever the last step ended."""
        for _ in range(5):
            if "adaptivelink" not in focused():
                sh("shell", "am", "start", "-n", "com.karthi.adaptivelink/.MainActivity")
                unlock_app()
            if has("Webcam", "Presenter"):
                return True
            back()
        return False

    def allow_permission():
        for label in ("While using the app", "Allow", "Only this time"):
            if tap(label, wait=1.5):
                return True
        return False

    # A real screen lock, so the app's own lock is exercised as it is on a
    # phone: with none set, the app has nothing to ask for and stays open.
    sh("shell", "locksettings", "set-pin", PIN)
    sh("shell", "svc", "power", "stayon", "true")

    def unlock_app():
        """Answer the app's unlock prompt with the PIN, if it is showing."""
        time.sleep(2)
        if not has("airing code") and not has("Connected") and not has("Not connected"):
            sh("shell", "input", "text", PIN)
            sh("shell", "input", "keyevent", "KEYCODE_ENTER")
            time.sleep(3)

    # The computer's owner, pressing Pair when the phone asks.
    def approve():
        """The owner's part, done here on the computer's side: wait for the
        phone's request, check the phone shows the same digits, press Pair.
        Returns (digits matched, the account the computer saw)."""
        for _ in range(120):
            state = control.call("GET", "/pair/state")
            if state.get("state") == "pending":
                time.sleep(1.5)
                matched = has(state["code"][:3])
                control.call("POST", "/pair/decide", {"accept": True})
                return matched, state.get("account", "")
            time.sleep(0.5)
        return False, ""

    def type_into(placeholder, text):
        tap(placeholder, wait=1)
        for start in range(0, len(text), 120):   # in pieces: adb drops long input
            sh("shell", "input", "text", text[start:start + 120])
        sh("shell", "input", "keyevent", "KEYCODE_BACK")   # hide the keyboard
        time.sleep(1)

    def pair_by_code():
        control.call("POST", "/unpair")
        started = control.call("POST", "/pair/start")
        offer = json.loads(started["payload"])
        if on_emulator:
            offer["h"] = [EMULATOR_HOST]
        text_code = "ALINK1." + base64.urlsafe_b64encode(json.dumps(offer).encode()).decode().rstrip("=")
        type_into("ALINK1\u2026", text_code)
        tap("Pair with this code", wait=1)
        matched, _account = approve()
        for _ in range(40):
            if has("Connected"):
                break
            time.sleep(1)
        return matched and has("Connected")

    def open_app():
        sh("shell", "am", "start", "-n", "com.karthi.adaptivelink/.MainActivity")
        unlock_app()

    sh("logcat", "-c")
    if on_emulator:
        # ------------------------------------------ by account, no code
        signed_in_as("someone-else@example.com")
        open_app()
        step(has("Sign in with Google", "Use a pairing code instead"),
             "first run: unlocked with the screen lock, then sign-in first and a pairing code as the other way")
        tap("Sign in with Google", wait=6)
        step(has("No computer is signed in as someone-else@example.com"),
             "sign-in: a phone on another account finds no computer there, and gets no further")
        step(control.call("GET", "/pair/state").get("state") != "pending", "sign-in: and the computer's owner is not asked")

        signed_in_as("me@example.com")
        open_app()
        step(tap("Sign out of", exact=False, wait=2) and has("Sign in with Google"),
             "sign-in: the phone signs out of that account")
        tap("Sign in with Google", wait=1)
        matched, account = approve()
        for _ in range(40):
            if has("Connected"):
                break
            time.sleep(1)
        step(matched and account == "me@example.com",
             "sign-in: with the computer's account the phone asks without a code, and shows the same six digits")
        step(has("Connected", "Screen", "Trackpad", "Presenter", "Webcam"), "sign-in: approved on the computer, connected")
    else:
        open_app()
        step(has("Use a pairing code instead") or has("Scan pairing code"), "first run: unlocked with the screen lock")
        tap("Use a pairing code instead")
        step(pair_by_code(), "code: a typed pairing code pairs the phone")

    # Power buttons are pressed below. With power turned off on the computer
    # they are refused, which is what is checked - a real lock or suspend
    # here would act on the machine running this test.
    control.call("POST", "/configure", {"allow_power": False})

    # ------------------------------------------------------------ screen
    def audited(action):
        return [e["detail"] for e in control.call("GET", "/log")["entries"] if e["action"] == action]

    tap("Screen", wait=4)
    for _ in range(15):
        if not has("Connecting"):
            break
        time.sleep(1)
    # "Connecting" goes only when a frame of video has been decoded and drawn.
    step(not has("Connecting") and not has("could not be started")
         and "video connected" in audited("screen-video"), "screen: the picture arrives, as video")
    tap("Picture and sound", wait=1.5)
    step(has("Low quality", "High quality") and has("Video: on", "Sound: on"), "screen: quality, video and sound are chosen in one place")
    tap("Low quality", wait=3)
    for _ in range(10):
        if not has("Connecting"):
            break
        time.sleep(1)
    step(not has("Connecting") and not has("could not be started") and any("video low" in d for d in audited("screen")),
         "screen: another quality starts the video again at that size")
    tap("Picture and sound", wait=1.5)
    tap("Video: on (less data)", wait=6)
    step(has("The computer's screen") and not has("Connecting") and audited("screen")[-1] == "low",
         "screen: with video off it arrives a picture at a time, as before")
    tap("Picture and sound", wait=1.5)
    tap("Video: off (a picture at a time)", wait=6)
    for label in ("Keyboard", "Scroll mode", "Scroll mode", "Keyboard"):
        tap(label, wait=1.2)
    step(has("Screen") and not has("could not be started"), "screen: video again, with the keyboard and scroll mode")
    sh("shell", "input", "tap", "540", "900")
    sh("shell", "input", "swipe", "400", "800", "700", "1000", "300")
    time.sleep(1)
    step(has("Screen"), "screen: a tap and a drag on the picture")
    home()

    # ---------------------------------------------------------- trackpad
    tap("Trackpad")
    sh("shell", "input", "swipe", "300", "700", "600", "900", "300")
    sh("shell", "input", "tap", "400", "800")
    for label in ("Left", "Right", "Esc", "Enter"):
        tap(label, wait=0.8)
    step(has("Drag to move"), "trackpad: move, tap, both buttons and the key row")
    home()

    # ------------------------------------------------------------- media
    tap("Media", wait=3)
    for label in ("Louder", "Quieter", "Mute"):
        tap(label, wait=0.8)
    step(has("Nothing is playing"), "media: the volume buttons, with nothing playing")
    home()

    # --------------------------------------------------------- presenter
    tap("Presenter")
    for label in ("Next", "Previous", "Start (F5)", "Blank", "End (Esc)", "Pause", "Reset"):
        tap(label, wait=0.7)
    sh("shell", "input", "keyevent", "KEYCODE_VOLUME_DOWN")
    sh("shell", "input", "keyevent", "KEYCODE_VOLUME_UP")
    time.sleep(1)
    step(has("Next", "Previous"), "presenter: every button, the timer, and the volume keys")
    home()

    # --------------------------------------------------------------- run
    tap("Run")
    if tap("A command to run on the computer", wait=1):
        sh("shell", "input", "text", "echo%sscreen-check")
        sh("shell", "input", "keyevent", "KEYCODE_ENTER")
        time.sleep(4)
    step(has("screen-check", "finished: 0"), "run: a command typed on the phone runs and its output is shown")
    tap("Save", wait=1.5)
    if tap("A name for its button", wait=1):
        sh("shell", "input", "text", "Greet")
        time.sleep(1)
    tap("Keep", wait=1.5)
    sh("shell", "input", "keyevent", "KEYCODE_BACK")   # the keyboard, if it is still up
    time.sleep(1)
    step(has("Greet") and not has("Keep"), "run: a command is kept as a button")
    control.call("POST", "/configure", {"allow_exec": True})
    before = len([e for e in control.call("GET", "/log")["entries"] if e["action"] == "exec"])
    tap("Greet", wait=4)
    after = len([e for e in control.call("GET", "/log")["entries"] if e["action"] == "exec"])
    step(after == before + 1 and has("finished: 0"), "run: and runs again with one tap")
    home()

    # ------------------------------------------------------------- files
    tap("Files", wait=3)
    step(tap("Downloads", wait=2.5) and has("movie.mkv"), "files: a folder opens")
    tap("movie.mkv", wait=1.5)
    step(has("Open on computer", "Download to phone"), "files: a file offers open and download")
    tap("Download to phone", wait=4)
    step(has("is in this phone"), "files: a file downloads to the phone")
    tap("Send a file to the computer", wait=3)
    step("adaptivelink" not in focused(), f"files: the picker for sending a file opens ({focused().strip()[-50:]})")
    back(2)
    step(home(), "files: back in the app after the picker")

    # ---------------------------------- tasks, devices, network, desktop
    tap("Tasks", wait=4)
    step(has("Memory", "Processor") and has("Load"), "tasks: the machine's load and its processes")
    tap("Memory", wait=2)
    if tap("Find a process", wait=1):
        sh("shell", "input", "text", "xvfb")
        sh("shell", "input", "keyevent", "KEYCODE_BACK")
        time.sleep(5)
    step(has("xvfb-run"), "tasks: a process is found by name")
    tap("xvfb-run", wait=1.5)
    step(has("End", "Kill", "Pause"), "tasks: a process can be paused, ended or killed")
    step(has("Priority", "And everything it started"), "tasks: its priority, and whether to act on what it started")
    tap("Low", wait=5)
    step(has("low priority"), "tasks: a process is made less important from the phone")
    home()

    tap("Devices", wait=4)
    step(has("USB", "Drives"), "devices: USB devices and drives")
    for _ in range(4):   # the mounted drive is further down the list
        if has("Browse"):
            break
        sh("shell", "input", "swipe", "540", "1700", "540", "700", "300")
        time.sleep(1)
    tap("Browse", wait=3)
    step(has("Send a file to the computer"), "devices: a drive opens in Files")
    home()

    def network_now():
        return json.loads((sandbox / "tools/network.json").read_text())

    tap("Network", wait=5)
    step(has("Received", "Sent"), "network: the connections and what they carry")
    step(reach("Look for networks") and has("Wi-Fi on the computer", "Cafe: Open", "Other"),
         "network: Wi-Fi and the networks in range")
    tap("Cafe: Open", wait=1.5)
    step(has("Join Cafe: Open?", "puts it back"), "network: a change that could cut the phone off is asked about first")
    tap("Go ahead", wait=6)
    time.sleep(KEEP_S + 3)
    step(network_now()["active"] == "Cafe: Open",
         "network: a network is joined from the phone, and kept because the phone still reaches the computer")
    reach("Other")
    tap("Other", wait=1.5)
    if tap("Password", wait=1):
        sh("shell", "input", "text", "correct-horse")
        time.sleep(1)
    tap("Join", wait=8)
    step(network_now()["active"] == "Other", "network: a network is joined with its password")
    reach("Work VPN")
    step(reach("DNS"), "network: the VPNs and the DNS servers")
    home()

    def machine_now():
        return json.loads((sandbox / "tools/machine.json").read_text())

    tap("Tasks", wait=5)
    step(has("Balanced", "Power saver"), "tasks: the power profile, beside the load")
    tap("Power saver", wait=4)
    step(machine_now()["profile"] == "balanced" and has("turned off on the computer"),
         "tasks: the power profile is not changed while the computer has power actions turned off")
    control.call("POST", "/configure", {"allow_power": True})   # the profile only: suspend and the rest are stand-ins here
    tap("Power saver", wait=4)
    control.call("POST", "/configure", {"allow_power": False})
    step(machine_now()["profile"] == "power-saver", "tasks: the power profile is changed from the phone")
    home()

    reach("Services")
    tap("Bluetooth", wait=5)
    step(has("Bluetooth on the computer", "Check Headphones", "Check Mouse"), "bluetooth: the devices the computer knows")
    tap("Connect", wait=5)
    step(len(machine_now()["connected"]) == 1 and has("Disconnect"), "bluetooth: a device is connected from the phone")
    home()

    reach("Services")
    tap("Display", wait=5)
    step(has("Displays", "Sound comes out of") and has("Check Speakers"), "display and sound: the displays and the sound devices")
    reach("Check Headset")
    tap("Use", wait=4)
    step(machine_now()["sink"] == "headset.check", "sound: another output is chosen from the phone")
    home()

    reach("Services")
    tap("Services", wait=5)
    step(has("sync", "backup") and has("running", "stopped"), "services: the owner's services and whether each runs")
    tap("backup", wait=1.5)
    tap("Start", wait=4)
    step("backup.service" in machine_now()["running"], "services: one is started from the phone")
    home()

    reach("Services")
    tap("Windows", wait=5)
    step(has("No windows are open"), "windows: says so when none are open (the checks' screen has no window manager)")
    home()

    tap("Desktop", wait=4)
    step(has("Quick note", "Focus") and has("Project"), "desktop: projects, notes, focus and windows")
    if tap("A line for the project's inbox", wait=1):
        sh("shell", "input", "text", "phone-note-check")
        sh("shell", "input", "keyevent", "KEYCODE_BACK")
        time.sleep(1)
    tap("Add note", wait=3)
    inbox = sandbox / "home/.local/share/adaptive-desktop/notes/General/Inbox.md"
    step(has("Noted in General") and inbox.exists() and "phone-note-check" in inbox.read_text(),
         "desktop: a note typed on the phone lands in the inbox on the computer")
    tap("Git", wait=3)
    step(has("Close"), "desktop: a report opens")
    tap("Close", wait=1)
    home()

    # ------------------------------------------------------------ webcam
    tap("Webcam", wait=3)
    allow_permission()
    time.sleep(4)
    # Whether the machine running this has the virtual camera decides which
    # of the two the app should say.
    installed = Path("/dev/video10").exists()
    step(has("Webcam") and has("virtual camera is not installed") != installed,
         "webcam: the camera opens, and says so if the computer has no virtual camera")
    tap("Switch camera", wait=3)
    step(has("Webcam"), "webcam: switching cameras")
    home()

    # ------------------------------------------------------------- share
    def share(text):
        sh("shell", "am", "start", "-n", "com.karthi.adaptivelink/.ShareActivity", "-a", "android.intent.action.SEND",
           "-t", "text/plain", "--es", "android.intent.extra.TEXT", text)
        time.sleep(4)

    def logged(action):
        return [e["detail"] for e in control.call("GET", "/log")["entries"] if e["action"] == action]

    share("https://example.org/shared-page")
    step(has("Send to", "Open on the computer", "Copy to its clipboard"), "share: a link shared from another app offers the computer")
    tap("Open on the computer", wait=4)
    step(has("Opened on the computer") and logged("open-url")[-1:] == ["https://example.org/shared-page"],
         "share: the link is opened on the computer")
    tap("Done", wait=1.5)
    share("remember-the-milk")
    step(has("Add to the project's notes") and not has("Open on the computer"), "share: plain text is not offered as a link")
    tap("Add to the project's notes", wait=4)
    inbox = sandbox / "home/.local/share/adaptive-desktop/notes/General/Inbox.md"
    step(has("Added to the project's inbox") and "remember-the-milk" in inbox.read_text(), "share: text is added to the computer's notes")
    tap("Done", wait=1.5)
    home()

    # -------------------------------------------------------------- more
    reach("More")
    tap("More", wait=2)
    tap("Get from computer", wait=2)
    tap("Send to computer", wait=2)
    step(has("Clipboard"), "more: clipboard both ways")
    tap("Lock", wait=2)
    step(has("turned off on the computer"), "more: a power action is refused when the computer has it turned off")
    tap("Suspend", wait=1.5)
    step(has("Cancel", "Yes"), "more: suspend asks first")
    tap("Cancel", wait=1)
    sh("shell", "input", "swipe", "540", "1500", "540", "600", "300")
    time.sleep(1)
    # The switch sits at the right-hand end of its label's row.
    for label, _x, y in nodes():
        if label == "Show them on the computer":
            sh("shell", "input", "tap", "980", str(y))
            break
    time.sleep(3)
    step("adaptivelink" not in focused() or has("Allow Adaptive Link"),
         "more: the notifications switch opens Android's notification access")
    if "adaptivelink" not in focused():
        back(2)
    home()
    reach("More")
    tap("More", wait=2)
    reach("The computer's own notifications as well")
    for label, _x, y in nodes():
        if label.startswith("Alerts on this phone"):
            sh("shell", "input", "tap", "980", str(y))
            break
    time.sleep(2)
    allow_permission()
    time.sleep(4)
    step("EventsService" in sh("shell", "dumpsys", "activity", "services", "com.karthi.adaptivelink"),
         "alerts: the phone stays listening once the owner turns them on")
    machine = json.loads((sandbox / "tools/machine.json").read_text())
    (sandbox / "tools/machine.json").write_text(json.dumps(dict(machine, failed=["sync.service"])))
    for _ in range(15):
        if "A service has failed" in sh("shell", "dumpsys", "notification", "--noredact"):
            break
        time.sleep(2)
    step("A service has failed" in sh("shell", "dumpsys", "notification", "--noredact"),
         "alerts: something going wrong on the computer is shown on the phone")
    home()
    reach("More")
    tap("More", wait=2)
    reach("Unpair this phone")
    step(tap("Unpair this phone", wait=1.5) and has("Unpair this phone?"), "more: unpairing asks first")
    tap("Unpair", wait=3)
    step(has("airing code") and not has("Sign out of"),
         "more: unpaired, the app is back at pairing and signed out of the account")

    # ------------------------------------------------- by pairing code
    if has("Use a pairing code instead"):
        step(tap("Use a pairing code instead"), "code: the other way to pair is offered")
    tap("Scan pairing code", wait=3)
    if "permission" in focused().lower():
        allow_permission()
    for _ in range(10):
        if "CaptureActivity" in focused():
            break
        time.sleep(1)
    step("CaptureActivity" in focused(), "code: Scan pairing code opens the camera scanner")
    back(2)
    step("MainActivity" in focused() and has("Scan pairing code"),
         "code: coming back from the scanner, the app is still open where it was (not locked, nothing lost)")

    # A phone that is not signed in to the account can still pair by code.
    step(pair_by_code(), "code: a typed pairing code pairs a phone that is not on the account")

    # ------------------------------------------------------ the app lock
    # Left for longer than the grace period, the app asks for the screen
    # lock again before it shows anything.
    sh("shell", "input", "keyevent", "KEYCODE_HOME")
    time.sleep(18)
    sh("shell", "am", "start", "-n", "com.karthi.adaptivelink/.MainActivity")
    time.sleep(3)
    step(not has("Screen", "Trackpad"), "lock: after being left, the app shows nothing until it is unlocked")
    sh("shell", "input", "text", PIN)
    sh("shell", "input", "keyevent", "KEYCODE_ENTER")
    time.sleep(3)
    step(has("Screen", "Trackpad"), "lock: the phone's own screen lock opens it")

    sh("shell", "am", "force-stop", "com.karthi.adaptivelink")
    sh("shell", "locksettings", "clear", "--old", PIN)


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
    # The network the app turns off and on is a stand-in, not this machine's.
    import fake_system_tools
    tools = sandbox / "tools"
    env.update(PATH=f"{fake_system_tools.install(tools / 'bin')}:{env['PATH']}", FAKE_TOOLS_DIR=str(tools),
               ADAPTIVE_LINK_KEEP_S=str(KEEP_S), ADAPTIVE_LINK_ALERT_EVERY_S="2",
               # No sound server here, and none is to be started by asking for one.
               PULSE_SERVER="unix:/nonexistent/pulse")
    env.pop("DBUS_SESSION_BUS_ADDRESS", None)
    daemon = subprocess.Popen(
        ["xvfb-run", "-a", "-s", "-screen 0 1280x800x24", "dbus-run-session", "--",
         sys.executable, str(LINK / "server.py")],
        env=env, stdout=open(sandbox / "daemon.log", "w"), stderr=subprocess.STDOUT,
        # Its own process group: stopping it has to reach the daemon inside
        # xvfb-run and dbus-run-session, not just the outermost wrapper.
        start_new_session=True)

    # Google, as far as this goes (scripts/fake_cloud.py). The emulator
    # reaches it, like the daemon, on the machine's own loopback.
    subprocess.Popen([sys.executable, str(REPO / "scripts/fake_cloud.py"), str(CLOUD_PORT)],
                     env=env, stdout=subprocess.DEVNULL, stderr=open(sandbox / "cloud.log", "w"))

    os.environ["XDG_RUNTIME_DIR"] = str(sandbox / "run")
    sys.path.insert(0, str(LINK))
    sys.path.insert(0, str(REPO / "scripts"))
    import control
    import fake_cloud
    try:
        for _ in range(100):
            try:
                control.status()
                break
            except control.NotRunning:
                time.sleep(0.2)
        # The computer signs in to its owner's account.
        on_emulator = devices[0].startswith("emulator-")
        cloud_url = f"http://127.0.0.1:{CLOUD_PORT}"
        control.call("POST", "/cloud/setup", fake_cloud.project(cloud_url))
        control.call("POST", "/cloud/signin")
        import urllib.request
        urllib.request.urlopen(urllib.request.Request(
            f"{cloud_url}/_test/approve", data=json.dumps({"email": "me@example.com"}).encode(),
            headers={"Content-Type": "application/json"}), timeout=10).read()
        for _ in range(100):
            if control.status().get("cloud") == "connected":
                break
            time.sleep(0.2)
        check(control.status().get("account") == "me@example.com", "the computer is signed in to its owner's account")

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
            [gradle(), "--no-daemon", "-q", "connectedDebugAndroidTest", ABIS,
             "-Pandroid.testInstrumentationRunnerArguments.class="
             "com.karthi.adaptivelink.LinkInstrumentedTest#pairThenUseTheLink",
             f"-Pandroid.testInstrumentationRunnerArguments.offer={encoded}"]
            + ([f"-Pandroid.testInstrumentationRunnerArguments.cloud={stand_in()}"] if on_emulator else []),
            cwd=APP, env=build_env, capture_output=True, text=True, timeout=1500)

        check(seen.get("name") == "Test Phone", f"the phone asked to pair, by name ({seen.get('name')})")
        check(done.returncode == 0, "the app paired with its keystore key, connected over mutual TLS, "
              "received the screen, ran a command, reached the computer through a direct connection "
              "set up by the account, and refused an impostor - on Android")
        if done.returncode != 0:
            print((done.stdout + done.stderr)[-3000:])
            print((sandbox / "daemon.log").read_text()[-3000:])
        state = control.status()
        check(state["phone"] is not None and state["phone"]["name"] == "Test Phone", "the computer holds the phone's certificate")
        log = control.call("GET", "/log")["entries"]
        actions = [entry["action"] for entry in log]
        check("exec" in actions and "screen" in actions, "the computer's audit log shows what the phone did")
        if on_emulator:
            check("tunnel" in actions, "the computer's audit log shows the direct connection being set up")
        check(daemon.poll() is None, "the daemon stayed up throughout")

        screens(check, adb, devices[0], control, build_env, sandbox)
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
