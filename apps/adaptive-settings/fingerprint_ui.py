"""Native fingerprint enrollment UI; all samples stay inside fprintd."""
import json
import shutil

from gi.repository import Gio, GLib, Gtk
from fingerprint_visual import FingerprintVisual

FINGERS = [f"{hand}-{finger}" for hand in ("right", "left")
           for finger in ("thumb", "index-finger", "middle-finger", "ring-finger", "little-finger")]
RETRY = {
    "enroll-retry-scan": "Try another touch with the same finger.",
    "enroll-swipe-too-short": "Swipe across the whole reader.",
    "enroll-finger-not-centered": "Center your finger on the reader.",
    "enroll-remove-and-retry": "Lift your finger, then touch the reader again.",
    "enroll-too-fast": "Keep your finger on the reader a little longer.",
}


def available_fingers(reader):
    return [finger for finger in FINGERS if finger not in reader.get("fingers", [])]


class FingerprintWindow(Gtk.Window):
    def __init__(self, parent, repo, run_async, changed):
        super().__init__(title="Fingerprint unlock", transient_for=parent, modal=True)
        self.set_default_size(560, 720)
        self.add_css_class("adaptive-settings")
        self.run_async, self.changed = run_async, changed
        self.helper = ["/usr/bin/python3", str(repo / "scripts/fingerprint.py")]
        self.proc = None
        self.busy = False
        self.last_finger = None
        self.closed = False
        self.timer = 0
        self.reader = {}
        self.choices = []
        self.registered = []
        self.passed = 0
        self.completed = False
        self.failure = ""
        self.mode = "enroll"
        self.connect("close-request", self._close)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        for side in ("top", "bottom", "start", "end"):
            getattr(body, "set_margin_" + side)(24)
        self.set_child(body)
        title = Gtk.Label(label="Your fingerprint, your laptop", xalign=0)
        title.add_css_class("card-title")
        body.append(title)
        self.saved = Gtk.Label(label="Checking your reader…", xalign=0, wrap=True)
        body.append(self.saved)
        body.append(Gtk.Label(label="Finger to register", xalign=0))
        self.finger = Gtk.DropDown.new_from_strings([])
        self.finger.add_css_class("choice")
        body.append(self.finger)
        body.append(Gtk.Label(label="Registered finger to test", xalign=0))
        self.test_finger = Gtk.DropDown.new_from_strings([])
        self.test_finger.add_css_class("choice")
        body.append(self.test_finger)
        self.visual = FingerprintVisual()
        body.append(self.visual)
        caption = Gtk.Label(label="Enrollment progress · fingerprint illustration")
        caption.add_css_class("card-subtitle")
        body.append(caption)
        self.spinner = Gtk.Spinner()
        self.spinner.set_halign(Gtk.Align.CENTER)
        body.append(self.spinner)
        self.progress = Gtk.ProgressBar(show_text=True)
        self.progress.add_css_class("fingerprint-progress")
        self.progress.set_text("Ready to scan")
        body.append(self.progress)
        self.message = Gtk.Label(label="", wrap=True, xalign=0)
        self.message.set_vexpand(True)
        body.append(self.message)
        self.result = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.CROSSFADE)
        self.result.set_transition_duration(round(self.visual.duration * 1000))
        self.result_label = Gtk.Label(label="", wrap=True, xalign=0)
        self.result.set_child(self.result_label)
        body.append(self.result)
        actions = Gtk.Box(spacing=12)
        self.enroll = Gtk.Button(label="Register finger", sensitive=False)
        self.enroll.add_css_class("accent")
        self.enroll.connect("clicked", lambda *_: self._prepare("enroll"))
        self.verify = Gtk.Button(label="Test recognition", sensitive=False)
        self.verify.add_css_class("quiet")
        self.verify.connect("clicked", lambda *_: self._prepare("verify"))
        self.cancel = Gtk.Button(label="Close")
        self.cancel.add_css_class("quiet")
        self.cancel.connect("clicked", lambda *_: self._cancel_or_close())
        for widget in (self.enroll, self.verify, self.cancel):
            actions.append(widget)
        body.append(actions)
        manage = Gtk.Button(label="Remove fingers in Ubuntu Users")
        manage.add_css_class("quiet")
        manage.connect("clicked", lambda *_: self._manage())
        body.append(manage)
        self.manage = manage
        self.sudo = Gtk.Button(label="Enable fingerprint for sudo")
        self.sudo.add_css_class("quiet")
        self.sudo.connect("clicked", lambda *_: self._enable_sudo())
        body.append(self.sudo)
        self._refresh()

    def _snapshot(self, callback):
        def loaded(ok, out, err):
            if self.closed:
                return
            try:
                data = json.loads(out) if ok else {}
            except ValueError:
                data = {}
            callback(data)
        self.run_async(self.helper + ["--json"], loaded)

    def _refresh(self):
        def loaded(data):
            if self.busy:
                return
            self.reader = next((r for r in data.get("readers", []) if r["default"]), {})
            fingers = self.reader.get("fingers", [])
            self.registered = fingers
            self.test_finger.set_model(Gtk.StringList.new([f.replace("-", " ").capitalize() for f in fingers]))
            self.test_finger.set_selected(fingers.index(self.last_finger) if self.last_finger in fingers else 0)
            self.test_finger.set_sensitive(bool(fingers))
            names = ", ".join(f.replace("-", " ").capitalize() for f in fingers)
            self.saved.set_text(f"{self.reader.get('name', 'No supported reader')}\nRegistered: {names or 'none'}")
            self.choices = available_fingers(self.reader)
            self.finger.set_model(Gtk.StringList.new([f.replace("-", " ").capitalize() for f in self.choices]))
            self.finger.set_selected(0)
            allowed = data.get("can_setup", False) and data.get("gdm_pam_present", False)
            self.enroll.set_sensitive(allowed and bool(self.choices) and bool(shutil.which("fprintd-enroll")))
            self.verify.set_sensitive(allowed and bool(fingers) and bool(shutil.which("fprintd-verify")))
            self.sudo.set_label("sudo: fingerprint or password enabled" if data.get("sudo_enabled") else "Enable fingerprint for sudo")
            self.sudo.set_sensitive(allowed and bool(fingers) and not data.get("sudo_enabled"))
            if not self.proc:
                if not allowed:
                    self.message.set_text(data.get("message", "Fingerprint service unavailable.") + " Check the GDM fingerprint packages.")
                elif data.get("session_policy_enabled") is False:
                    self.message.set_text("Fingerprint login is disabled. Open Ubuntu Users below to enable it.")
                else:
                    self.message.set_text("Choose another finger to register, or test a registered finger. Your password remains available.")
        self._snapshot(loaded)

    def _prepare(self, mode):
        if self.busy:
            return
        selected = self.finger.get_selected() if mode == "enroll" else self.test_finger.get_selected()
        choices = self.choices if mode == "enroll" else self.registered
        finger = choices[selected] if selected < len(choices) else None
        self._busy(True)
        self.message.set_text("Checking the reader…")
        def checked(data):
            reader = next((r for r in data.get("readers", []) if r["default"]), {})
            if (not data.get("can_setup") or not data.get("gdm_pam_present") or
                    (mode == "enroll" and finger not in available_fingers(reader)) or
                    (mode == "verify" and finger not in reader.get("fingers", []))):
                self._busy(False)
                self._show_result("Reader or registered fingers changed. Please try again.")
                self._refresh()
                return
            self.reader = reader
            def enabled(ok, out, err):
                if self.closed:
                    return
                if not ok:
                    self._busy(False)
                    self._show_result(out or err or "Fingerprint login is disabled by policy.")
                    self._refresh()
                    return
                self._start(mode, finger)
            self.run_async(self.helper + ["--enable-login"], enabled)
        self._snapshot(checked)

    def _busy(self, busy):
        self.busy = busy
        for widget in (self.enroll, self.verify, self.finger, self.test_finger, self.manage, self.sudo):
            widget.set_sensitive(not busy)
        self.cancel.set_label("Cancel" if busy else "Close")
        self.spinner.set_spinning(busy)

    def _start(self, mode, finger):
        self.last_finger = finger
        self.mode, self.passed, self.completed, self.failure = mode, 0, False, ""
        self.visual.update("scanning", 0, self.reader.get("stages", 1) if mode == "enroll" else 1)
        self.result.set_reveal_child(False)
        self.progress.set_fraction(0)
        self.progress.set_text("Waiting for your touch")
        launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE)
        launcher.setenv("LC_ALL", "C", True)
        try:
            self.proc = launcher.spawnv(self._command(mode, finger))
        except GLib.Error as error:
            self.visual.update("failed")
            self._busy(False)
            self._show_result(error.message)
            self._refresh()
            return
        self.stream = Gio.DataInputStream.new(self.proc.get_stdout_pipe())
        self.message.set_text((f"Touch the reader with your {finger.replace('-', ' ')}. Lift and touch again after each sample."
                               if mode == "enroll" else f"Touch the reader with your {finger.replace('-', ' ')}."))
        self.timer = GLib.timeout_add_seconds(90, self._timeout)
        self._read()

    @staticmethod
    def _command(mode, finger):
        argv = ["fprintd-enroll" if mode == "enroll" else "fprintd-verify", "-f", finger]
        return ["stdbuf", "-oL", "-eL"] + argv

    def _read(self):
        self.stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self._line)

    def _line(self, stream, result):
        try:
            line, _ = stream.read_line_finish_utf8(result)
        except GLib.Error:
            line = None
        if line is None:
            self.proc.wait_async(None, self._exited)
            return
        if not self.closed:
            value = (line.split(":", 1)[-1].strip().split() or [""])[0]
            if value == "enroll-stage-passed":
                self.passed += 1
                stages = max(1, self.reader.get("stages", 1))
                self.visual.update("accepted", self.passed, stages)
                self.progress.set_fraction(min(self.passed / stages, .95))
                self.progress.set_text(f"{self.passed} samples accepted")
                self.message.set_text("Sample accepted. Lift your finger, then place its center on the reader again.")
            elif value in ("enroll-completed", "verify-match"):
                self.completed = True
                self.progress.set_fraction(1)
                self.progress.set_text("Fingerprint saved" if self.mode == "enroll" else "Fingerprint recognized")
            elif value in RETRY:
                self.visual.update("retry")
                self.message.set_text(RETRY[value])
            elif value in ("verify-retry-scan", "verify-swipe-too-short", "verify-finger-not-centered", "verify-remove-and-retry", "verify-too-fast"):
                self.visual.update("retry")
                self.message.set_text("Lift your finger, center it on the reader, and try again.")
            elif value.startswith(("enroll-", "verify-")):
                self.failure = "Fingerprint was not recognized." if value == "verify-no-match" else "Scan did not finish: " + value
            elif "error" in line.lower() or "failed" in line.lower():
                self.failure = line
        self._read()

    def _exited(self, proc, result):
        proc.wait_finish(result)
        self.proc = None
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0
        if self.closed:
            return
        self._busy(False)
        self.cancel.set_sensitive(True)
        if self.completed and proc.get_successful() and not self.failure:
            self.visual.update("saved" if self.mode == "enroll" else "verified", self.visual.stages)
            self._show_result("Finger registered. You can add another finger or test recognition." if self.mode == "enroll" else "Recognition succeeded. You can now test screen unlock.")
        else:
            self.visual.update("failed")
            self.progress.set_text("Not recognized" if self.mode == "verify" else "Enrollment incomplete")
            self._show_result(self.failure or "The scan did not finish. You can try again.")
        self._refresh()
        self.changed()

    def _show_result(self, text):
        self.result_label.set_text(text)
        self.result.set_reveal_child(True)

    def _timeout(self):
        self.timer = 0
        if self.proc:
            self.failure = "Scan timed out. Please try again when ready."
            self.proc.force_exit()
        return GLib.SOURCE_REMOVE

    def _cancel_or_close(self):
        if self.proc:
            self.failure = "Scan cancelled."
            self.proc.force_exit()
            self.cancel.set_sensitive(False)
        else:
            self.close()

    def _manage(self):
        self.run_async(self.helper + ["--setup"], lambda *_: self._refresh() if not self.closed else None)

    def _enable_sudo(self):
        self._busy(True)
        def enabled(ok, out, err):
            if self.closed:
                return
            self._busy(False)
            self._show_result("sudo now accepts fingerprints with password fallback." if ok else out or err or "Administrator authorization was not completed.")
            self._refresh()
        self.run_async(self.helper + ["--enable-sudo"], enabled)

    def _close(self, *_):
        self.closed = True
        self.visual.update("idle")
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0
        if self.proc:
            self.proc.force_exit()
        self.changed()
        return False
