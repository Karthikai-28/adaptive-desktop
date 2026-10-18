#!/usr/bin/env python3
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path


# This checkout, wherever it was cloned.
REPO = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("ADAPTIVE_STATE_DIR", Path.home() / ".config" / "adaptive-desktop"))
SESSION_STATE = STATE_DIR / "session-state.json"


def facts():
    return {
        "desktop": os.environ.get("XDG_CURRENT_DESKTOP", ""),
        "session_desktop": os.environ.get("XDG_SESSION_DESKTOP", ""),
        "session_type": os.environ.get("XDG_SESSION_TYPE", ""),
        "dconf_profile": os.environ.get("DCONF_PROFILE", ""),
        "adaptive_session_entry": Path("/usr/share/xsessions/adaptive-desktop.desktop").exists(),
        "ubuntu_session_entry": Path("/usr/share/xsessions/ubuntu.desktop").exists(),
        "adaptive_shell_installed": (Path.home() / ".local/share/gnome-shell/extensions/adaptive-shell@local").exists(),
    }


def status(_args):
    print(json.dumps(facts(), indent=2, sort_keys=True))
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


RECOVERY_STEPS = [
    "gnome-extensions disable adaptive-shell@local",
    f"cd {shlex.quote(str(REPO))} && ./scripts/remove-adaptive-session.sh",
    f"{shlex.quote(str(REPO / 'scripts/session-cli.py'))} login ubuntu",
]

# Session id and display server GDM starts for each choice. GDM logs a user in
# to the session AccountsService remembers for them, so setting it here picks
# the session without the login screen's gear menu. Changing your own account
# needs no password.
LOGIN_SESSIONS = {
    "adaptive": ("adaptive-desktop", "x11"),
    "ubuntu": ("ubuntu", "wayland"),
    "ubuntu-xorg": ("ubuntu-xorg", "x11"),
}


def _accounts_user(method, *args):
    path = f"/org/freedesktop/Accounts/User{os.getuid()}"
    return subprocess.run(
        ["gdbus", "call", "--system", "--dest", "org.freedesktop.Accounts",
         "--object-path", path, "--method", method, *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def login(args):
    if args.session:
        session, session_type = LOGIN_SESSIONS[args.session]
        _accounts_user("org.freedesktop.Accounts.User.SetSession", session)
        _accounts_user("org.freedesktop.Accounts.User.SetXSession", session)
        _accounts_user("org.freedesktop.Accounts.User.SetSessionType", session_type)
    current = _accounts_user("org.freedesktop.DBus.Properties.Get",
                             "org.freedesktop.Accounts.User", "Session")
    current = current.strip("(<'>,)")
    print(f"Next login: {current or 'GDM default (ubuntu)'}")
    return 0


def recover(_args):
    for command in RECOVERY_STEPS:
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
    login_parser = sub.add_parser("login", help="show or set the session GDM logs you in to")
    login_parser.add_argument("session", nargs="?", choices=sorted(LOGIN_SESSIONS))
    login_parser.set_defaults(func=login)
    args = parser.parse_args()

    try:
        raise SystemExit(args.func(args))
    except Exception as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
