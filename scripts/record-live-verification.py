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
        "id": "clipboard_history",
        "backlog": "Clipboard history in the Command palette.",
        "prompt": "Copy two snippets, type \"clip\" in the palette (Alt+Space): are both listed, and does Enter copy one back?",
    },
    {
        "id": "project_park_resume",
        "backlog": "Project snapshots: park and resume.",
        "prompt": "From the project menu in the top bar, Park then Resume: do the windows close and come back in place?",
    },
    {
        "id": "project_indicator",
        "backlog": "Active project and git status in the top bar.",
        "prompt": "Is the active project shown top left with its branch, and does the ± count change after editing a file?",
    },
    {
        "id": "screen_text",
        "backlog": "Copy text from screen.",
        "prompt": "With tesseract-ocr installed, does Control Center > Copy Text from Screen put the selected words on the clipboard?",
    },
    {
        "id": "phone_link",
        "backlog": "Phones in the Network panel.",
        "prompt": "With KDE Connect or GSConnect paired, does the Network panel list the phone, and do Ring and Send file work?",
    },
    {
        "id": "watchdog",
        "backlog": "Crash watchdog.",
        "prompt": "After a normal day of use, does Adaptive Settings show the watchdog as Armed (never stood down by accident)?",
    },
    {
        "id": "dropdown_terminal",
        "backlog": "Drop-down terminal.",
        "prompt": "Does Super+Return drop a terminal from the top of the screen in the project folder, and hide it again?",
    },
    {
        "id": "annotate",
        "backlog": "Annotate a screenshot.",
        "prompt": "Does Super+Shift+S let you select an area, draw on it, and paste the result (Ctrl+C) into another app?",
    },
    {
        "id": "palette_modes",
        "backlog": "Command palette modes.",
        "prompt": "In the palette, do \"git\", \"todo\", \"/some text\" and \"keys\" each list what they should for your real projects?",
    },
    {
        "id": "clipboard_pins_images",
        "backlog": "Clipboard pins and images.",
        "prompt": "In \"clip\", does Ctrl+P pin an entry so it survives Clear Clipboard History, and is a copied image listed and pasted back?",
    },
    {
        "id": "link_phone",
        "backlog": "Adaptive Link from the real phone.",
        "prompt": "Paired with your own phone: do the screen, trackpad, media, presenter, run, files and notifications all work on Wi-Fi?",
    },
    {
        "id": "link_away",
        "backlog": "Adaptive Link away from home.",
        "prompt": "Signed in with Google on both, with the phone on mobile data: does Adaptive Link connect (\"Direct, away\") and show the screen?",
    },
    {
        "id": "link_camera",
        "backlog": "Phone camera as webcam.",
        "prompt": "After install-link-camera.sh, does a browser or meeting app list \"Phone Camera\" and show the phone's picture?",
    },
    {
        "id": "link_system_control",
        "backlog": "Adaptive Link changing the real network and drives.",
        "prompt": "From the phone: does joining another Wi-Fi network with its password work, does Wi-Fi turned off come back on by itself within a minute, and does Safely remove release a real USB drive?",
    },
    {
        "id": "link_video_sound",
        "backlog": "Adaptive Link: the screen as video with sound on a real phone.",
        "prompt": "On your phone's Screen page: does the picture arrive as video, and can you hear what the computer is playing?",
    },
    {
        "id": "link_machine_real",
        "backlog": "Adaptive Link changing real Bluetooth, displays and sound devices.",
        "prompt": "From the phone: does connecting a Bluetooth device, changing brightness and choosing another sound output each work on the real machine?",
    },
    {
        "id": "link_wake",
        "backlog": "Adaptive Link waking the computer.",
        "prompt": "After link-cli.py wake on, with the computer suspended and the phone on its network: does \"Wake it\" wake it?",
    },
    {
        "id": "link_alerts_widget",
        "backlog": "Adaptive Link alerts, widget and tiles on a real phone.",
        "prompt": "With alerts on, does a notification on the computer appear on the phone - and do the home-screen widget and the quick-settings tiles lock the computer and pause what is playing?",
    },
    {
        "id": "link_relay",
        "backlog": "Adaptive Link through a relay of your own.",
        "prompt": "With a TURN server set by link-cli.py relay, does the phone connect from a network where a direct connection fails?",
    },
    {
        "id": "link_together",
        "backlog": "Adaptive Link: the phone and the computer together, on a real phone.",
        "prompt": "With the switches on: does text copied on the computer paste on the phone, does link-cli.py ring make it ring, and does the computer lock when the phone leaves the Wi-Fi and unlock on your fingerprint when it returns?",
    },
    {
        "id": "link_sudo",
        "backlog": "Adaptive Link: sudo approved by the phone.",
        "prompt": "After install-link-sudo.sh: does sudo ask the phone, accept your fingerprint, and still take the password when the phone is away?",
    },
    {
        "id": "link_phone_hardware",
        "backlog": "Adaptive Link: what needs a real phone's hardware.",
        "prompt": "On a real phone: does Air on the Trackpad move the pointer, does the microphone type what you say, does a written NFC tag press its button, and does the phone's microphone appear as Phone Microphone in a meeting app?",
    },
    {
        "id": "link_second_display",
        "backlog": "Adaptive Link: the phone as another display.",
        "prompt": "Does \"Use this phone as another display\" give a display to the right of the main one that windows can be dragged onto, and does it go away on leaving the screen?",
    },
    {
        "id": "link_ask",
        "backlog": "Adaptive Link: asking in words, on the real machine.",
        "prompt": "From the phone's ask box and from the palette: do \"turn off bluetooth\", \"what's using the memory\" and Undo each do what they say on the real machine?",
    },
    {
        "id": "link_phone_window",
        "backlog": "Adaptive Link: the phone's screen in a window on the computer.",
        "prompt": "Does \"Show it there now\" open your phone's screen in a window, and with accessibility allowed, do clicks, drags and typing in it act on the phone?",
    },
    {
        "id": "link_extended_display",
        "backlog": "Adaptive Link: the phone as another display (evdi).",
        "prompt": "After install-link-display.sh and restarting the link: does \"Use this phone as another display\" add a display you can drag windows onto, shown on the phone?",
    },
    {
        "id": "link_widgets_nearby",
        "backlog": "Adaptive Link: widgets, and pairing by being near.",
        "prompt": "Do the four widgets work on your home screen, and does a second phone on the Wi-Fi see the computer as nearby while the pairing window is open?",
    },
    {
        "id": "link_app_workspaces",
        "backlog": "Adaptive Link: every app from the phone, in a workspace of its own.",
        "prompt": "From Apps, do Files, a browser, a terminal, an editor, a media player and Impress each open into a workspace - moved to the phone's display where it is installed, a crop that follows the window where it is not - upright, sideways, full screen and with the keyboard up?",
    },
    {
        "id": "link_layouts_sync",
        "backlog": "Adaptive Link: several saved layouts per app, kept on the computer and each phone.",
        "prompt": "Save three layouts for one app, restart the phone and the computer: are all three there? Edit one on a second phone: does the first receive it, and do two edits made at once both survive?",
    },
    {
        "id": "link_macro_cancel",
        "backlog": "Adaptive Link: buttons of several steps, stopped part-way.",
        "prompt": "Run a button that opens an app, waits for its window, types and presses keys; press Stop part-way. Do the remaining steps not happen, is no key left held down, and does nothing run again on reconnecting over Wi-Fi, USB and mobile data?",
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


def record_result(check_id, result, note=""):
    """Record one result and return the report path; None for an unknown id."""
    known = {check["id"]: check for check in CHECKS}
    if check_id not in known:
        return None

    report = latest_report()
    report.setdefault("checks", {})
    report["checks"][check_id] = {
        "result": result,
        "note": note,
        "recorded_at": int(time.time()),
        "backlog": known[check_id]["backlog"],
    }
    report["updated_at"] = int(time.time())
    # The Shade shows "N of total"; it cannot read CHECKS itself.
    report["total"] = len(CHECKS)
    return write_report(report)


def record(args):
    path = record_result(args.check_id, args.result, args.note)
    if path is None:
        print(f"Unknown check id: {args.check_id}", file=sys.stderr)
        return 1

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
