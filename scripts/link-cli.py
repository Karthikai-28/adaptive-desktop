#!/usr/bin/env python3
"""Adaptive Link from the command line.

    link-cli.py status         is it on, which phone, which account
    link-cli.py setup [FILE]   tell the link about your Google project (once)
    link-cli.py signin         sign this computer in to your Google account
    link-cli.py signout        sign it out and remove it from the account
    link-cli.py pair           pair by code instead (opens a window with a QR)
    link-cli.py unpair         forget the paired phone
    link-cli.py on | off       start or stop accepting the phone
    link-cli.py allow input|exec|files|power on|off
                               what the phone may do (input: pointer, keyboard
                               and launching apps; off, it can only watch)
    link-cli.py allow account on|off
                               whether a device signed in to your account may
                               ask to connect without a pairing code
    link-cli.py allow auto-approve on|off
                               whether such a device is accepted without asking
    link-cli.py log            what the phone has done

The daemon is services/adaptive-link (systemd unit adaptive-link.service).
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "services" / "adaptive-link"))
import control  # noqa: E402


def describe(state):
    """The status as lines of text."""
    lines = []
    if state.get("problem"):
        lines.append(f"Adaptive Link has a problem: {state['problem']}")
    elif not state["enabled"]:
        lines.append("Adaptive Link is off.")
    elif not state["phone"]:
        lines.append("Adaptive Link is on, with no phone paired.")
    else:
        lines.append(f"Adaptive Link is on, port {state['port']}.")

    cloud = state.get("cloud", "not set up")
    if state.get("account"):
        approval = "connect without asking" if state["config"].get("auto_approve_account") else "ask to connect, without a code"
        lines.append(f"Signed in as {state['account']} ({cloud}): your devices on this account can {approval},")
        lines.append("  and reach this computer directly from other networks.")
    elif cloud == "not set up":
        lines.append("Google account: not set up (link-cli.py setup). Pairing is by code, on this network only.")
    else:
        lines.append(f"Google account: {cloud} (link-cli.py signin).")

    phone = state["phone"]
    if phone:
        when = time.strftime("%Y-%m-%d", time.localtime(phone["paired_at"]))
        lines.append(f"Paired phone: {phone['name']} (since {when})")
    for item in state["addresses"]:
        lines.append(f"  {item['address']:<16} this network")
    config = state["config"]
    allowed = [name for name, key in (("pointer and keyboard", "allow_input"), ("commands", "allow_exec"),
                                      ("files", "allow_files"), ("power", "allow_power")) if config[key]]
    lines.append("The phone may: see the screen, media, clipboard, notifications"
                 + (", " + ", ".join(allowed) if allowed else ""))
    if config["allow_input"] and not config["allow_exec"]:
        lines.append("  Note: with pointer and keyboard on, commands can still be typed into a terminal.")
    lines.append("Phone camera as webcam: " + (state["camera"] or "not installed (scripts/install-link-camera.sh)"))
    if state["viewing"]:
        lines.append("The phone is viewing the screen now.")
    if state.get("direct"):
        lines.append("The phone is connected directly from another network.")
    return lines


SETUP_QUESTIONS = (
    ("api_key", "Web API Key (Firebase > Project settings > General)"),
    ("database_url", "Realtime Database URL (https://...firebaseio.com or ...firebasedatabase.app)"),
    ("web_client_id", "Web client ID (Cloud console > Credentials > Web client)"),
    ("device_client_id", "TV / Limited Input client ID"),
    ("device_client_secret", "TV / Limited Input client secret"),
)


def do_setup(path):
    """Tell the link about the owner's Google project (docs/ADAPTIVE_LINK.md)."""
    if path:
        values = json.loads(Path(path).read_text(encoding="utf-8"))
    else:
        print("Your Google project's details (docs/ADAPTIVE_LINK.md says where each one is):")
        values = {key: input(f"  {question}: ").strip() for key, question in SETUP_QUESTIONS}
    if not control.call("POST", "/cloud/setup", values)["ok"]:
        print("Those details are incomplete, or the database address is not an https one.")
        return 1
    print("Saved. Now sign in: link-cli.py signin")
    return 0


def do_signin():
    started = control.call("POST", "/cloud/signin")
    if not started.get("ok"):
        print(f"Could not start signing in: {started.get('error')}")
        return 1
    print(f"On any device where you are signed in to Google, open:\n\n    {started['url']}\n")
    print(f"and enter this code:\n\n    {started['code']}\n")
    print("Waiting for you to approve it...")
    for _ in range(360):
        time.sleep(5)
        signin = control.status().get("signin", {})
        if signin.get("state") == "done":
            print(f"Signed in as {signin['email']}.")
            return 0
        if signin.get("state") == "failed":
            print(f"Sign-in did not complete: {signin.get('error')}")
            return 1
    print("Timed out waiting.")
    return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="Adaptive Link")
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("status", "pair", "unpair", "on", "off", "log", "signin", "signout"):
        sub.add_parser(name)
    setup = sub.add_parser("setup")
    setup.add_argument("file", nargs="?", help="a JSON file with the five values, instead of typing them")
    allow = sub.add_parser("allow")
    allow.add_argument("what", choices=["input", "exec", "files", "power", "account", "auto-approve"])
    allow.add_argument("state", choices=["on", "off"])
    args = parser.parse_args(argv)

    try:
        if args.action == "status":
            print("\n".join(describe(control.status())))
        elif args.action == "setup":
            return do_setup(args.file)
        elif args.action == "signin":
            return do_signin()
        elif args.action == "signout":
            done = control.call("POST", "/cloud/signout")["ok"]
            print("Signed out; this computer is no longer in the account." if done else "Not signed in.")
        elif args.action == "pair":
            return subprocess.call([sys.executable, str(REPO / "services/adaptive-link/pair_window.py")])
        elif args.action == "unpair":
            removed = control.call("POST", "/unpair")["ok"]
            print("The phone is forgotten; it can no longer connect." if removed else "No phone was paired.")
        elif args.action in ("on", "off"):
            state = control.call("POST", "/enable", {"enabled": args.action == "on"})
            # One line: this is also what the palette shows in a notification.
            print(describe(state)[0])
        elif args.action == "allow":
            key = {"account": "account_enroll", "auto-approve": "auto_approve_account"}.get(
                args.what, f"allow_{args.what}")
            state = control.call("POST", "/configure", {key: args.state == "on"})
            print("\n".join(describe(state)))
        elif args.action == "log":
            for entry in control.call("GET", "/log")["entries"]:
                print(f"{entry['at']}  {entry['from'] or '-':<16} {entry['action']:<18} {entry['detail']}")
    except control.NotRunning:
        print("Adaptive Link is not running (systemctl --user start adaptive-link).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
