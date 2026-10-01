#!/usr/bin/env python3
"""Run a command and say how it went, in a notification.

The Command palette closes the moment you press Enter, so a command it starts
has nowhere to report to. This runs one and notifies: the title and the last
line of output on success, the last few lines on failure.

    adaptive-run-notify.py "Switch to main" -- git -C ~/code/thing switch main

The command is an argument list, never a shell string.
"""

import subprocess
import sys

TIMEOUT_S = 120
SHOWN_LINES = 4


def summarize(returncode, output):
    """(ok, body) for the notification."""
    lines = [line.strip() for line in (output or "").splitlines() if line.strip()]
    if returncode == 0:
        return True, lines[-1] if lines else "Done"
    tail = "\n".join(lines[-SHOWN_LINES:]) if lines else f"Exited with status {returncode}"
    return False, tail


def main(argv):
    if "--" not in argv or argv.index("--") != 2 or len(argv) < 4:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    title, command = argv[1], argv[3:]
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=TIMEOUT_S)
        ok, body = summarize(done.returncode, done.stdout + done.stderr)
    except subprocess.TimeoutExpired:
        ok, body = False, f"Still running after {TIMEOUT_S} seconds; stopped"
    except OSError as error:
        ok, body = False, str(error)
    subprocess.run(
        ["notify-send", "--app-name=Adaptive Command",
         f"--icon={'emblem-ok-symbolic' if ok else 'dialog-warning-symbolic'}",
         title if ok else f"{title} failed", body],
        check=False)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
