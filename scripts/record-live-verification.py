#!/usr/bin/env python3
import argparse
import json
import sys
import time
from pathlib import Path


REPO = Path.home() / "adaptive-desktop"
REPORT_DIR = REPO / "verification"

CHECKS = [
    {
        "id": "tty_recovery",
        "backlog": "Test recovery from TTY.",
        "prompt": "From Ctrl+Alt+F3, can you log in, disable adaptive-shell@local, and return safely?",
    },
    {
        "id": "rail_strut",
        "backlog": "Reserve application area above the bottom dock.",
        "prompt": "After reloading Adaptive Shell, do maximized/tiled windows avoid the bottom dock?",
    },
    {
        "id": "project_autostart",
        "backlog": "Verify service autostart inside Adaptive Desktop.",
        "prompt": "After logging into Adaptive Desktop, does project-cli.py status work without manually starting the service?",
    },
    {
        "id": "workspace_overview",
        "backlog": "Workspace overview redesign.",
        "prompt": "Does the Workspaces/Home overview render with Adaptive styling and usable workspace switching?",
    },
    {
        "id": "multi_monitor",
        "backlog": "Multi-monitor behavior.",
        "prompt": "With an external monitor attached, do bottom-dock placement and window presets behave correctly?",
    },
    {
        "id": "audio_output",
        "backlog": "Audio output selection submenu exists and needs live device verification.",
        "prompt": "With more than one output device available, can System Center switch audio output?",
    },
    {
        "id": "restart_shutdown_confirmation",
        "backlog": "Restart and shut down entries use GNOME-native confirmation actions where available.",
        "prompt": "Do Restart and Shut Down open the expected GNOME-native confirmation flow?",
    },
    {
        "id": "nautilus_project_preview",
        "backlog": "Nautilus preview has a Project tab backed by Project Context Service.",
        "prompt": "Does the Nautilus preview/inspector Project tab show Project Context data?",
    },
    {
        "id": "lock_treatment",
        "backlog": "Adaptive lock treatment.",
        "prompt": "After locking and unlocking, is the experience usable and visually compatible?",
    },
    {
        "id": "login_compatibility",
        "backlog": "Login compatibility.",
        "prompt": "Can Adaptive Desktop and normal Ubuntu both be selected and started from GDM?",
    },
    {
        "id": "gdm_fallback",
        "backlog": "GDM fallback test.",
        "prompt": "After logout, can you choose normal Ubuntu from GDM and get a working stock session?",
    },
    {
        "id": "reboot",
        "backlog": "Reboot test.",
        "prompt": "After reboot, can you log into Adaptive Desktop and run the stability suite?",
    },
    {
        "id": "suspend_resume",
        "backlog": "Suspend/resume test.",
        "prompt": "After suspend/resume, do shell, input, windows, and project status still work?",
    },
    {
        "id": "external_monitor",
        "backlog": "External monitor test.",
        "prompt": "After attach/detach of an external monitor, does the desktop remain usable?",
    },
    {
        "id": "long_memory",
        "backlog": "Long-running shell memory test.",
        "prompt": "Did scripts/verify-shell-memory.py --seconds 14400 --interval 60 pass in the graphical session?",
    },
]


def latest_report():
    path = REPORT_DIR / "live-verification-latest.json"
    if not path.exists():
        return {"checks": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def write_report(report):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = REPORT_DIR / f"live-verification-{stamp}.json"
    latest = REPORT_DIR / "live-verification-latest.json"
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")
    latest.write_text(text, encoding="utf-8")
    return path


def print_check(check):
    print(f"{check['id']}: {check['backlog']}")
    print(f"  {check['prompt']}")


def list_checks(_args):
    for check in CHECKS:
        print_check(check)
    return 0


def status(_args):
    report = latest_report()
    checks = report.get("checks", {})
    for check in CHECKS:
        entry = checks.get(check["id"], {})
        state = entry.get("result", "pending")
        note = entry.get("note", "")
        suffix = f" - {note}" if note else ""
        print(f"{state.upper():7} {check['id']}{suffix}")
    return 0


def record(args):
    known = {check["id"]: check for check in CHECKS}
    if args.check_id not in known:
        print(f"Unknown check id: {args.check_id}", file=sys.stderr)
        return 1

    report = latest_report()
    report.setdefault("checks", {})
    report["checks"][args.check_id] = {
        "result": args.result,
        "note": args.note,
        "recorded_at": int(time.time()),
        "backlog": known[args.check_id]["backlog"],
    }
    report["updated_at"] = int(time.time())
    path = write_report(report)
    print(f"Recorded {args.check_id}: {args.result}")
    print(f"Report: {path}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Record Adaptive Desktop live verification results")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List live verification checks").set_defaults(func=list_checks)
    sub.add_parser("status", help="Show latest recorded status").set_defaults(func=status)

    record_parser = sub.add_parser("record", help="Record a check result")
    record_parser.add_argument("check_id")
    record_parser.add_argument("result", choices=["pass", "fail", "na"])
    record_parser.add_argument("--note", default="")
    record_parser.set_defaults(func=record)

    args = parser.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
