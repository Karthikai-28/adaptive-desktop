#!/usr/bin/env python3
"""Switch the power profile when the charger is plugged in or pulled out.

On battery: the profile you chose for battery (power-saver by default). On
mains: the one you chose for mains (balanced by default). It only changes the
profile at the moment the power source changes, so a profile you pick by hand
stays until the next time you plug or unplug.

Off unless you turn it on:

    adaptive-power-auto.py --enable [--battery power-saver] [--ac balanced]
    adaptive-power-auto.py --disable
    adaptive-power-auto.py --status       what it would do, changing nothing
    adaptive-power-auto.py                run (services/adaptive-power-auto.service)

This never touches suspend, the lid or screen blanking: docs/POWER_POLICY.md
puts those out of reach of any feature, and this one keeps to that. It talks to
power-profiles-daemon and UPower, the same two services GNOME's own menu uses.

Settings: ~/.config/adaptive-desktop/power.json
"""

import argparse
import json
import sys
from pathlib import Path

CONFIG = Path.home() / ".config" / "adaptive-desktop" / "power.json"
DEFAULTS = {"auto_profile": False, "battery": "power-saver", "ac": "balanced"}
KNOWN_PROFILES = ("power-saver", "balanced", "performance")

UPOWER = ("org.freedesktop.UPower", "/org/freedesktop/UPower", "org.freedesktop.UPower")
PROFILES = ("net.hadess.PowerProfiles", "/net/hadess/PowerProfiles", "net.hadess.PowerProfiles")


def load_config(path=None):
    """The settings, with anything missing or malformed replaced by a default."""
    config = dict(DEFAULTS)
    try:
        data = json.loads((path or CONFIG).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return config
    if isinstance(data, dict):
        config["auto_profile"] = data.get("auto_profile") is True
        for key in ("battery", "ac"):
            if data.get(key) in KNOWN_PROFILES:
                config[key] = data[key]
    return config


def save_config(config, path=None):
    path = path or CONFIG
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def wanted_profile(on_battery, config, available):
    """The profile to switch to for this power source, or None to leave it.

    None when the feature is off, and when the machine does not offer the
    profile asked for (performance is missing on many laptops): better to do
    nothing than to pick something else on the user's behalf.
    """
    if not config.get("auto_profile"):
        return None
    profile = config["battery" if on_battery else "ac"]
    return profile if profile in available else None


class Daemon:
    def __init__(self):
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
        self.Gio, self.GLib = Gio, GLib
        self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        self.on_battery = None

    def _get(self, target, name):
        reply = self.bus.call_sync(
            target[0], target[1], "org.freedesktop.DBus.Properties", "Get",
            self.GLib.Variant("(ss)", (target[2], name)), None,
            self.Gio.DBusCallFlags.NONE, 3000, None)
        return reply.unpack()[0]

    def state(self):
        """(on_battery, active_profile, available_profiles)."""
        return (bool(self._get(UPOWER, "OnBattery")), self._get(PROFILES, "ActiveProfile"),
                [p["Profile"] for p in self._get(PROFILES, "Profiles")])

    def set_profile(self, profile):
        self.bus.call_sync(
            PROFILES[0], PROFILES[1], "org.freedesktop.DBus.Properties", "Set",
            self.GLib.Variant("(ssv)", (PROFILES[2], "ActiveProfile", self.GLib.Variant("s", profile))),
            None, self.Gio.DBusCallFlags.NONE, 3000, None)

    def apply(self):
        on_battery, active, available = self.state()
        # Only when the source changes: a profile chosen by hand since the last
        # change is the user's, and stays.
        if on_battery == self.on_battery:
            return
        self.on_battery = on_battery
        profile = wanted_profile(on_battery, load_config(), available)
        if profile and profile != active:
            self.set_profile(profile)
            print(f"{'battery' if on_battery else 'mains'}: {active} -> {profile}", flush=True)

    def run(self):
        self.bus.signal_subscribe(
            UPOWER[0], "org.freedesktop.DBus.Properties", "PropertiesChanged", UPOWER[1],
            None, self.Gio.DBusSignalFlags.NONE, lambda *_: self._guarded(), )
        # The source at start is not a change: leave whatever is set.
        self.on_battery = self.state()[0]
        self.GLib.MainLoop().run()

    def _guarded(self):
        try:
            self.apply()
        except Exception as error:  # noqa: BLE001 - keep listening
            print(f"power profile not changed: {error}", file=sys.stderr, flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Switch power profile with the power source")
    parser.add_argument("--enable", action="store_true")
    parser.add_argument("--disable", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--battery", choices=KNOWN_PROFILES)
    parser.add_argument("--ac", choices=KNOWN_PROFILES)
    args = parser.parse_args(argv)

    if args.enable or args.disable or args.battery or args.ac:
        config = load_config()
        if args.enable:
            config["auto_profile"] = True
        if args.disable:
            config["auto_profile"] = False
        for key in ("battery", "ac"):
            if getattr(args, key):
                config[key] = getattr(args, key)
        save_config(config)

    if args.status or args.enable or args.disable or args.battery or args.ac:
        config = load_config()
        print(f"Automatic power profile: {'on' if config['auto_profile'] else 'off'}")
        print(f"  on battery: {config['battery']}    on mains: {config['ac']}")
        try:
            on_battery, active, available = Daemon().state()
        except Exception as error:  # noqa: BLE001 - status must not fail on a desktop without the daemon
            print(f"  power-profiles-daemon or UPower is not answering: {error}")
            return 0
        print(f"  now: {'battery' if on_battery else 'mains'}, profile {active}; this machine offers {', '.join(available)}")
        for source, key in (("battery", True), ("mains", False)):
            profile = wanted_profile(key, config, available)
            if config["auto_profile"] and profile is None:
                print(f"  note: {config['battery' if key else 'ac']} is not offered here, so nothing changes on {source}")
        return 0

    try:
        Daemon().run()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
