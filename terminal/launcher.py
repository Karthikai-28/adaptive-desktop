#!/usr/bin/env python3
"""Open Terminal with the KTERM modern profile, preserving command arguments.

Also installed as gnome-terminal and x-terminal-emulator for desktop callers
that still use those command names. The system binaries remain available.
"""

import os
from pathlib import Path
import shlex
import shutil
import sys


def terminal_args(args, caller="kterm-terminal"):
    result = []
    while args:
        arg, *args = args
        if arg in ("--", "-x", "--execute") or (caller != "gnome-terminal" and arg == "-e"):
            return [*result, "-x", *args]
        if caller == "gnome-terminal" and arg in ("-e", "--command"):
            if not args:
                raise ValueError(f"{arg} needs a command")
            return [*result, "-x", *shlex.split(args[0]), *args[1:]]
        if caller == "gnome-terminal" and arg in ("--wait", "--window", "--tab", "--disable-factory"):
            continue  # --no-dbus opens a dedicated process and waits for it.
        if caller == "gnome-terminal" and (arg == "--profile" or arg.startswith("--profile=")):
            if arg == "--profile":
                if not args:
                    raise ValueError("--profile needs a value")
                args = args[1:]
            continue
        result.append(arg)
    return result


def main():
    config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    profile = config / "karthi-shell/terminator-modern.conf"
    binary = shutil.which("terminator")
    if not binary or not profile.is_file():
        raise SystemExit("Terminal needs the KTERM modern profile and Terminator installed.")
    args = terminal_args(sys.argv[1:], Path(sys.argv[0]).name)
    env = os.environ.copy()
    env["KARTHI_SHELL_MODE"] = "modern"
    for key in ("KARTHI_MODERN_LOADED", "KARTHI_HUD_SHOWN"):
        env.pop(key, None)
    os.execve(binary, [binary, "--no-dbus", "--config", str(profile),
                      "--profile", "modern", "--icon", "kterm-terminal", *args], env)


if __name__ == "__main__":
    main()
