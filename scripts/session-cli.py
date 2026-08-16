#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import time
from pathlib import Path


STATE_DIR = Path(os.environ.get("ADAPTIVE_STATE_DIR", Path.home() / ".config" / "adaptive-desktop"))
SESSION_STATE = STATE_DIR / "session-state.json"


def status(_args):
    facts = {
        "desktop": os.environ.get("XDG_CURRENT_DESKTOP", ""),
        "session_desktop": os.environ.get("XDG_SESSION_DESKTOP", ""),
        "session_type": os.environ.get("XDG_SESSION_TYPE", ""),
        "dconf_profile": os.environ.get("DCONF_PROFILE", ""),
        "adaptive_session_entry": Path("/usr/share/xsessions/adaptive-desktop.desktop").exists(),
        "ubuntu_session_entry": Path("/usr/share/xsessions/ubuntu.desktop").exists(),
        "adaptive_shell_installed": (Path.home() / ".local/share/gnome-shell/extensions/adaptive-shell@local").exists(),
    }
    print(json.dumps(facts, indent=2, sort_keys=True))
    return 0


def save(_args):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "saved_at": int(time.time()),
        "desktop": os.environ.get("XDG_CURRENT_DESKTOP", ""),
        "session_desktop": os.environ.get("XDG_SESSION_DESKTOP", ""),
        "dconf_profile": os.environ.get("DCONF_PROFILE", ""),
    }
    SESSION_STATE.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Saved session state: {SESSION_STATE}")
    return 0


def recover(_args):
    commands = [
        "gnome-extensions disable adaptive-shell@local",
        "cd ~/adaptive-desktop && ./scripts/remove-adaptive-session.sh",
        "Choose Ubuntu from the GDM gear menu",
    ]
    for command in commands:
        print(command)
    return 0


def logout(_args):
    result = subprocess.run(["gnome-session-quit", "--logout", "--no-prompt"], check=False)
    return result.returncode


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Adaptive Desktop session controls")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status").set_defaults(func=status)
    sub.add_parser("save").set_defaults(func=save)
    sub.add_parser("recover").set_defaults(func=recover)
    sub.add_parser("logout").set_defaults(func=logout)
    args = parser.parse_args()

    try:
        raise SystemExit(args.func(args))
    except Exception as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
