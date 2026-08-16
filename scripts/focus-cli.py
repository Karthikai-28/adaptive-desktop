#!/usr/bin/env python3
import argparse
import subprocess
import sys
import time


SCHEMA = "org.gnome.desktop.notifications"
KEY = "show-banners"


def gsettings(*args):
    return subprocess.run(
        ["gsettings", *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def set_focus(enabled):
    # Focus enabled means notification banners are hidden.
    value = "false" if enabled else "true"
    result = gsettings("set", SCHEMA, KEY, value)
    if result.returncode:
        print(result.stderr.strip() or "Unable to update notification focus state", file=sys.stderr)
        return 1
    return 0


def status(_args):
    result = gsettings("get", SCHEMA, KEY)
    if result.returncode:
        print(result.stderr.strip() or "Unable to read notification focus state", file=sys.stderr)
        return 1

    show_banners = result.stdout.strip() == "true"
    print("Focus: off" if show_banners else "Focus: on")
    return 0


def on(_args):
    return set_focus(True)


def off(_args):
    return set_focus(False)


def timer(args):
    minutes = max(1, args.minutes)
    if set_focus(True):
        return 1

    print(f"Focus: on for {minutes} minute(s)")
    try:
        time.sleep(minutes * 60)
    except KeyboardInterrupt:
        pass

    return set_focus(False)


def main():
    parser = argparse.ArgumentParser(description="Adaptive Desktop focus controls")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show focus state").set_defaults(func=status)
    sub.add_parser("on", help="Hide notification banners").set_defaults(func=on)
    sub.add_parser("off", help="Show notification banners").set_defaults(func=off)

    timer_parser = sub.add_parser("timer", help="Enable focus for a number of minutes")
    timer_parser.add_argument("minutes", type=int)
    timer_parser.set_defaults(func=timer)

    args = parser.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
