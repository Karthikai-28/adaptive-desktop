#!/usr/bin/env python3
"""Run on a virtual display; fixture subprocesses never access the real reader."""
import sys
import time
import subprocess
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Gdk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/adaptive-settings"))
from fingerprint_ui import FingerprintWindow, available_fingers

DATA = {"can_setup": True, "gdm_pam_present": True, "session_policy_enabled": True,
        "sudo_enabled": True, "readers": [{"name": "Validity VFS7552", "default": True,
        "fingers": ["right-index-finger"], "stages": 6}]}


def until(predicate, seconds=4):
    deadline = time.monotonic() + seconds
    ctx = GLib.MainContext.default()
    while time.monotonic() < deadline:
        while ctx.pending(): ctx.iteration(False)
        if predicate(): return
        time.sleep(.01)
    raise AssertionError("UI operation timed out")


def main():
    Gtk.init()
    provider = Gtk.CssProvider()
    provider.load_from_path(str(ROOT / "apps/adaptive-settings/style.css"))
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    parent = Gtk.Window()
    # This fixture also blocks the helper's status and policy subprocesses.
    import json
    def run(argv, callback): callback(True, json.dumps(DATA), "")
    window = FingerprintWindow(parent, ROOT, run, lambda: None)
    window.present()
    if "--screenshot" in sys.argv:
        until(lambda: window.get_width() > 1)
        # Allow the first render to finish on the isolated X display.
        loop = GLib.MainLoop()
        GLib.timeout_add(300, lambda: (loop.quit(), False)[1])
        loop.run()
        (ROOT / "build").mkdir(exist_ok=True)
        subprocess.run(["import", "-window", "root", str(ROOT / "build/fingerprint-enrollment.png")], check=True)
    assert len(available_fingers(DATA["readers"][0])) == 9
    assert "right-index-finger" not in window.choices
    assert window.registered == ["right-index-finger"]
    assert window._command("verify", "left-thumb")[-3:] == ["fprintd-verify", "-f", "left-thumb"]
    window._prepare("enroll")
    assert not window.busy and window.proc is None
    assert "Choose the finger" in window.active_finger.get_text()
    window.visual.update("accepted", 3, 6)
    until(lambda: abs(window.visual.fraction - .5) < .01)
    window.visual.update("retry")
    assert window.visual.accepted == 3 and window.visual.target == .5
    settings = Gtk.Settings.get_default()
    animations = settings.get_property("gtk-enable-animations")
    settings.set_property("gtk-enable-animations", False)
    window.visual.update("accepted", 4)
    assert window.visual.fraction == 4 / 6
    settings.set_property("gtk-enable-animations", animations)
    commands = []
    def command(source):
        def fixture(mode, finger):
            commands.append((mode, finger))
            return [sys.executable, "-u", "-c", source]
        window._command = fixture
    def select_finger(finger="left-index-finger"):
        window.finger.set_selected(window.choices.index(finger) + 1)
    command("import time; print('Enroll result: enroll-stage-passed'); time.sleep(.15); print('Enroll result: enroll-completed')")
    select_finger()
    window._prepare("enroll")
    assert commands[-1] == ("enroll", "left-index-finger")
    assert window.active_finger.get_text() == "Registering: Left index finger"
    DATA["readers"][0]["fingers"].append("left-index-finger")
    assert window.spinner.get_spinning() and not window.enroll.get_sensitive()
    until(lambda: window.proc is None)
    assert "Finger registered" in window.result_label.get_text()
    assert window.visual.phase == "saved"
    assert window.progress.get_fraction() == 1 and not window.spinner.get_spinning()
    command("print('Verify result: verify-match (done)')")
    window._prepare("verify")
    assert commands[-1] == ("verify", "left-index-finger")
    assert window.active_finger.get_text() == "Testing: Left index finger"
    until(lambda: window.proc is None)
    assert "Recognition succeeded" in window.result_label.get_text()
    assert window.visual.phase == "verified"
    command("import sys; print('Verify result: verify-no-match (done)'); sys.exit(1)")
    window._prepare("verify")
    until(lambda: window.proc is None)
    assert "not recognized" in window.result_label.get_text()
    assert window.visual.phase == "failed"
    command("import time; time.sleep(30)")
    select_finger("left-thumb")
    window._prepare("enroll")
    window._cancel_or_close()
    until(lambda: window.proc is None)
    assert "cancelled" in window.result_label.get_text()
    select_finger("left-thumb")
    window._prepare("enroll")
    GLib.source_remove(window.timer)
    window._timeout()
    until(lambda: window.proc is None)
    assert "timed out" in window.result_label.get_text()
    select_finger("left-thumb")
    window._prepare("enroll")
    window.close()
    until(lambda: window.proc is None)
    assert window.closed and window.timer == 0 and window.visual.tick == 0
    parent.destroy()
    print("Fingerprint UI: multiple fingers, animation, success, rejection, cancel, timeout and close passed")


if __name__ == "__main__":
    main()
