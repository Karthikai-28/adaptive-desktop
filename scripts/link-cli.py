#!/usr/bin/env python3
"""Adaptive Link from the command line.

    link-cli.py status         is it on, which phone, which addresses
    link-cli.py pair           show the pairing QR code (opens a window)
    link-cli.py unpair         forget the paired phone
    link-cli.py on | off       start or stop accepting the phone
    link-cli.py allow exec|files|power on|off
                               what the phone may do
    link-cli.py allow account on|off
                               whether a device signed in to your account may
                               ask to connect without a pairing code
    link-cli.py allow auto-approve on|off
                               whether such a device is accepted without asking
    link-cli.py log            what the phone has done

The daemon is services/adaptive-link (systemd unit adaptive-link.service).
"""

import argparse
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
        lines.append("Adaptive Link is on, with no phone paired (link-cli.py pair).")
    else:
        lines.append(f"Adaptive Link is on, port {state['port']}.")
    if state.get("account"):
        approval = "connect without asking" if state["config"].get("auto_approve_account") else "ask to connect, without a code"
        lines.append(f"Signed in as {state['account']}: your other devices on this account can {approval}.")
    phone = state["phone"]
    if phone:
        when = time.strftime("%Y-%m-%d", time.localtime(phone["paired_at"]))
        lines.append(f"Paired phone: {phone['name']} (since {when})")
    for item in state["addresses"]:
        label = "Tailscale (works from anywhere)" if item["kind"] == "tailscale" else "local network"
        lines.append(f"  {item['address']:<16} {label}")
    if not state["tailscale"]:
        lines.append("  Tailscale is not connected: the phone can reach this computer on the local network only.")
    config = state["config"]
    allowed = [name for name, key in (("commands", "allow_exec"), ("files", "allow_files"),
                                      ("power", "allow_power")) if config[key]]
    lines.append("The phone may: screen and input, media, clipboard, notifications"
                 + (", " + ", ".join(allowed) if allowed else ""))
    lines.append("Phone camera as webcam: " + (state["camera"] or "not installed (scripts/install-link-camera.sh)"))
    if state["viewing"]:
        lines.append("The phone is viewing the screen now.")
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description="Adaptive Link")
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("status", "pair", "unpair", "on", "off", "log"):
        sub.add_parser(name)
    allow = sub.add_parser("allow")
    allow.add_argument("what", choices=["exec", "files", "power", "account", "auto-approve"])
    allow.add_argument("state", choices=["on", "off"])
    args = parser.parse_args(argv)

    try:
        if args.action == "status":
            print("\n".join(describe(control.status())))
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
