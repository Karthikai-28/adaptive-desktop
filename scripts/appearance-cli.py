#!/usr/bin/env python3
import argparse
import subprocess
import sys


def gsettings(*args):
    result = subprocess.run(
        ["gsettings", *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        print(result.stderr.strip(), file=sys.stderr)
    return result


def reduced_motion(args):
    value = "false" if args.state == "on" else "true"
    return gsettings("set", "org.gnome.desktop.interface", "enable-animations", value).returncode


def high_contrast(args):
    theme = "HighContrast" if args.state == "on" else "Yaru-dark"
    return gsettings("set", "org.gnome.desktop.interface", "gtk-theme", theme).returncode


def color_scheme(args):
    scheme = "prefer-light" if args.mode == "light" else "prefer-dark"
    return gsettings("set", "org.gnome.desktop.interface", "color-scheme", scheme).returncode


def status(_args):
    for schema, key in [
        ("org.gnome.desktop.interface", "enable-animations"),
        ("org.gnome.desktop.interface", "gtk-theme"),
        ("org.gnome.desktop.interface", "color-scheme"),
    ]:
        result = gsettings("get", schema, key)
        if not result.returncode:
            print(f"{key}: {result.stdout.strip()}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Adaptive Desktop appearance controls")
    sub = parser.add_subparsers(dest="command", required=True)

    rm = sub.add_parser("reduced-motion", help="Toggle reduced motion")
    rm.add_argument("state", choices=["on", "off"])
    rm.set_defaults(func=reduced_motion)

    hc = sub.add_parser("high-contrast", help="Toggle high contrast")
    hc.add_argument("state", choices=["on", "off"])
    hc.set_defaults(func=high_contrast)

    scheme = sub.add_parser("scheme", help="Set color scheme")
    scheme.add_argument("mode", choices=["dark", "light"])
    scheme.set_defaults(func=color_scheme)

    sub.add_parser("status", help="Show appearance state").set_defaults(func=status)

    args = parser.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
