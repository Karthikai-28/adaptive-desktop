#!/usr/bin/env python3
"""Detect usable readers through fprintd; delegate enrollment to GNOME Users.

Never read biometric templates or implement authentication. GDM and GNOME's
lock screen own authentication through their existing pam_fprintd service.
"""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

BUS = "net.reactivated.Fprint"
MANAGER = "/net/reactivated/Fprint/Manager"
DEVICE = BUS + ".Device"


class ProbeError(Exception):
    def __init__(self, name, message):
        super().__init__(message)
        self.name = name


class Fprint:
    def __init__(self):
        from gi.repository import Gio, GLib
        self.Gio, self.GLib = Gio, GLib
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        except GLib.Error as error:
            raise ProbeError("bus-unavailable", error.message) from error

    def call(self, path, interface, method, signature=None, args=()):
        try:
            return self.bus.call_sync(
                BUS, path, interface, method,
                self.GLib.Variant(signature, args) if signature else None,
                None, self.Gio.DBusCallFlags.NONE, 5000, None).unpack()[0]
        except self.GLib.Error as error:
            name = self.Gio.DBusError.get_remote_error(error) or "service-error"
            raise ProbeError(name, error.message) from error

    def devices(self):
        return self.call(MANAGER, BUS + ".Manager", "GetDevices")

    def default_device(self):
        return self.call(MANAGER, BUS + ".Manager", "GetDefaultDevice")

    def name(self, path):
        return self.call(path, "org.freedesktop.DBus.Properties", "Get",
                         "(ss)", (DEVICE, "name"))

    def fingers(self, path):
        # Empty username means the calling user. Only finger names are returned.
        return self.call(path, DEVICE, "ListEnrolledFingers", "(s)", ("",))

    def stages(self, path):
        return self.call(path, "org.freedesktop.DBus.Properties", "Get",
                         "(ss)", (DEVICE, "num-enroll-stages"))


def probe(factory=Fprint):
    result = {"state": "unavailable", "readers": [], "can_setup": False}
    try:
        service = factory()
        paths = service.devices()
        default = service.default_device() if paths else None
        for path in paths:
            name = service.name(path)
            try:
                fingers = service.fingers(path)
            except ProbeError as error:
                if error.name != BUS + ".Error.NoEnrolledPrints":
                    raise
                fingers = []
            result["readers"].append({"name": name, "enrolled": len(fingers),
                                      "fingers": fingers, "default": path == default,
                                      "stages": service.stages(path)})
    except (ProbeError, ImportError) as error:
        result["message"] = (
            "Fingerprint service unavailable. Install fprintd, libpam-fprintd and "
            "python3-gi from Ubuntu, then retry in your desktop session.")
        result["error"] = str(error)
        return result
    if not result["readers"]:
        result.update(state="no-supported-reader", message=(
            "No supported fingerprint reader detected. A reader may be absent, "
            "disabled in firmware, or unsupported by the installed driver."))
    else:
        enrolled = sum(r["enrolled"] for r in result["readers"])
        result.update(state="enrolled" if enrolled else "enrollment-required", can_setup=True,
                      message=(f"{enrolled} finger(s) registered. Verify recognition before testing screen unlock."
                               if enrolled else "Reader detected. Register a finger in Users → Fingerprint Login."))
    return result


def login_policy():
    """Current session policy only; the greeter can have its own dconf policy."""
    try:
        from gi.repository import Gio
        source = Gio.SettingsSchemaSource.get_default()
        schema = source.lookup("org.gnome.login-screen", True) if source else None
        if not schema:
            return None
        return Gio.Settings.new_full(schema, None, None)
    except ImportError:
        return None


def status():
    result = probe()
    settings = login_policy()
    result["session_policy_enabled"] = settings.get_boolean("enable-fingerprint-authentication") if settings else None
    try:
        lines = Path("/etc/pam.d/gdm-fingerprint").read_text().splitlines()
        result["gdm_pam_present"] = any(
            line.strip().startswith("auth") and "pam_fprintd.so" in line.split()
            for line in lines if not line.lstrip().startswith("#"))
    except OSError:
        result["gdm_pam_present"] = False
    try:
        common = Path("/etc/pam.d/common-auth").read_text()
        sudo = Path("/etc/pam.d/sudo").read_text()
        active = [line for line in common.splitlines() if not line.lstrip().startswith("#")]
        result["sudo_enabled"] = (
            any("pam_fprintd.so" in line.split() for line in active) and
            any("pam_unix.so" in line.split() for line in active) and
            any(line.strip() == "@include common-auth" for line in sudo.splitlines()))
    except OSError:
        result["sudo_enabled"] = False
    return result


def enable_login(result):
    if not result["can_setup"]:
        return 1
    if not result["gdm_pam_present"]:
        print("GDM fingerprint authentication is missing. Restore Ubuntu's gdm3 and libpam-fprintd packages first.")
        return 1
    settings = login_policy()
    key = "enable-fingerprint-authentication"
    if settings is None:
        print("GNOME login policy is unavailable.")
        return 1
    if not settings.get_boolean(key):
        if not settings.is_writable(key) or not settings.set_boolean(key, True):
            print("Fingerprint login is disabled by policy. Ask the administrator to enable it.")
            return 1
        from gi.repository import Gio
        Gio.Settings.sync()
    return 0


def setup(result):
    if enable_login(result):
        return 1
    if not shutil.which("gnome-control-center"):
        print("Install gnome-control-center to register and manage fingers.")
        return 1
    return subprocess.call(["gnome-control-center", "user-accounts"])


def enable_sudo(result):
    if not result["can_setup"] or not any(r["enrolled"] for r in result["readers"]):
        print("Register and test a finger before enabling fingerprint authentication for sudo.")
        return 1
    if result["sudo_enabled"]:
        return 0
    if not Path("/usr/share/pam-configs/fprintd").is_file() or not shutil.which("pkexec"):
        print("Install libpam-fprintd and policykit-1 first.")
        return 1
    # Use the distribution's profile ordering and password fallback. Never force
    # an overwrite of locally customized PAM stacks or write authentication code.
    rc = subprocess.call(["pkexec", "/usr/sbin/pam-auth-update", "--enable", "fprintd"])
    if rc:
        return rc
    if not status()["sudo_enabled"]:
        print("PAM has local customizations; review it with sudo pam-auth-update. No configuration was forced.")
        return 1
    print("Fingerprint authentication enabled, with password fallback. Shared PAM services use it too.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable status")
    parser.add_argument("--setup", action="store_true", help="enable session policy and open native enrollment for a detected reader")
    parser.add_argument("--enable-login", action="store_true", help="enable the current session's fingerprint login policy")
    parser.add_argument("--enable-sudo", action="store_true", help="enable Ubuntu's PAM fingerprint profile, with an administrator dialog")
    parser.add_argument("--install-status", action="store_true", help="report only missing setup to install.sh")
    args = parser.parse_args()
    result = status()
    if args.install_status:
        if result["state"] == "no-supported-reader":
            print("skipped: " + result["message"])
        elif result["state"] != "enrolled":
            print(result["message"])
        elif not result["gdm_pam_present"] or not result["session_policy_enabled"]:
            print("Fingerprint login needs setup in Adaptive Settings.")
        return 0
    if args.json:
        print(json.dumps(result))
    else:
        print(result["message"])
        for reader in result["readers"]:
            print(f"  {reader['name']}: {reader['enrolled']} finger(s)")
        if result["can_setup"]:
            if not result["gdm_pam_present"]:
                print("GDM fingerprint PAM service is missing.")
            if result["session_policy_enabled"] is False:
                print("Fingerprint login is disabled for this session; use --setup to enable it.")
    if args.enable_sudo:
        return enable_sudo(result)
    if args.enable_login:
        return enable_login(result)
    return setup(result) if args.setup else 0


if __name__ == "__main__":
    raise SystemExit(main())
