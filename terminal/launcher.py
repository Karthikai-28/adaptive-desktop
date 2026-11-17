#!/usr/bin/env python3
"""Open Terminal with the KTERM modern profile, preserving command arguments.

Also installed as gnome-terminal and x-terminal-emulator for desktop callers
that still use those command names. The system binaries remain available.
"""

import os
from pathlib import Path
import runpy
import shlex
import shutil
import sys


def terminal_args(args, caller="kterm-terminal"):
    result = []
    while args:
        arg, *args = args
        if arg in ("--", "-x", "--execute"):
            return [*result, "-x", *args]
        if arg in ("-e", "--command"):
            if not args:
                raise ValueError(f"{arg} needs a command")
            cmd = args[0]
            rest = args[1:]
            if len(rest) == 0 and " " in cmd:
                return [*result, "-x", *shlex.split(cmd)]
            return [*result, "-x", cmd, *rest]
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
    # A phone session (Adaptive Link) has a config folder of its own; the
    # profile is still the one installed in the laptop's.
    homes = [Path(os.environ["XDG_CONFIG_HOME"])] if os.environ.get("XDG_CONFIG_HOME") else []
    homes.append(Path.home() / ".config")
    profile = next((home / "karthi-shell/terminator-modern.conf" for home in homes
                    if (home / "karthi-shell/terminator-modern.conf").is_file()), homes[0] / "karthi-shell/terminator-modern.conf")
    binary = shutil.which("terminator")
    if not binary or not profile.is_file():
        raise SystemExit("Terminal needs the KTERM modern profile and Terminator installed.")
    args = terminal_args(sys.argv[1:], Path(sys.argv[0]).name)
    env = os.environ.copy()
    env["KARTHI_SHELL_MODE"] = "modern"
    # bat draws with the terminal's own sixteen colours instead of a theme of its own.
    env.setdefault("BAT_THEME", "ansi")
    for key in ("KARTHI_MODERN_LOADED", "KARTHI_HUD_SHOWN"):
        env.pop(key, None)
    cmd_args = [binary, "--no-dbus", "--config", str(profile),
                "--profile", "modern", "--icon", "kterm-terminal", *args]
    os.environ.clear()
    os.environ.update(env)
    try:
        import gi
        gi.require_version("Gdk", "3.0")
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gdk, GLib
        GLib.set_prgname("kterm-terminal")
        Gdk.set_program_class("kterm-terminal")
        sys.argv = cmd_args
        runpy.run_path(binary, run_name="__main__")
    except SystemExit as exc:
        sys.exit(exc.code)
    except Exception:
        os.execve(binary, cmd_args, env)


if __name__ == "__main__":
    main()
