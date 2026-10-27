#!/usr/bin/env python3
"""Open agy, claude or codex in a terminal, as one session the laptop and the phone share.

    adaptive-agent claude            a session not already open on this screen
    adaptive-agent claude --new      always a new session
    adaptive-agent claude DIR        a new session starts in DIR

Each agent runs inside a private tmux server (socket "adaptive-agents"), in
the owner's login shell with the laptop's own environment, wherever it was
opened from. The phone session (Adaptive Link) attaches to the same session
the laptop terminal shows, so a conversation started on one continues on the
other. When the agent exits its shell stays, in the same folder.

Installed as ~/.local/bin/adaptive-agent by scripts/install-terminal.py.
"""

import json
import os
from pathlib import Path
import pwd
import re
import shlex
import shutil
import subprocess
import sys


AGENTS = {"claude": "Claude Code", "codex": "Codex", "agy": "Antigravity CLI"}
SOCKET = os.environ.get("ADAPTIVE_AGENT_SOCKET", "adaptive-agents")
# What the phone session (or any other launcher) adds that must not reach an
# agent: it would talk to the phone's display and bus, at the phone's scale.
# (phone_form.environment and mobile_session.start).
FOREIGN = ("ADAPTIVE_MOBILE_ROOT", "ADAPTIVE_PHONE_", "GDK_SCALE", "GDK_DPI_SCALE", "GDK_BACKEND", "GTK_USE_PORTAL",
           "GTK_OVERLAY_SCROLLING", "_JAVA_OPTIONS", "QT_SCALE_FACTOR", "QT_AUTO_SCREEN_SCALE_FACTOR",
           "QT_ENABLE_HIGHDPI_SCALING", "QT_QUICK_CONTROLS_", "QT_QPA_PLATFORM", "XCURSOR_SIZE", "PULSE_",
           "TMUX", "KARTHI_MODERN_LOADED", "KARTHI_HUD_SHOWN", "VSCODE_", "TERM_PROGRAM", "DESKTOP_STARTUP_ID",
           "XDG_ACTIVATION_TOKEN")
# Without systemd's copy, a phone's display, bus and settings are the
# phone's, never the laptop's.
PHONE_SESSION = ("DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS", "DCONF_PROFILE", "XDG_RUNTIME_DIR",
                 "XDG_CONFIG_DIRS", "XDG_CURRENT_DESKTOP", "XDG_SESSION_TYPE")


def config_file():
    homes = [Path(os.environ["XDG_CONFIG_HOME"])] if os.environ.get("XDG_CONFIG_HOME") else []
    homes.append(Path.home() / ".config")
    for path in [home / "karthi-shell/agents.tmux.conf" for home in homes] + [Path(__file__).with_name("agents.tmux.conf")]:
        if path.is_file():
            return path
    raise SystemExit("adaptive-agent needs agents.tmux.conf; run scripts/install-terminal.py --apply")


def laptop_env():
    """The graphical session's environment, as systemd keeps it for the
    owner, whichever display this was started from."""
    env = {}
    if os.environ.get("ADAPTIVE_AGENT_ENV") != "inherit":
        # A phone session has a runtime folder and bus of its own, where
        # systemctl would not find the owner's manager.
        runtime = f"/run/user/{os.getuid()}"
        reach = dict(os.environ, XDG_RUNTIME_DIR=runtime, DBUS_SESSION_BUS_ADDRESS=f"unix:path={runtime}/bus")
        try:
            out = subprocess.run(["systemctl", "--user", "show-environment"], env=reach,
                                 capture_output=True, text=True, timeout=5).stdout
            env = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
        except (OSError, subprocess.TimeoutExpired):
            pass
    if not env.get("DISPLAY") and not env.get("WAYLAND_DISPLAY"):
        phone = bool(os.environ.get("ADAPTIVE_MOBILE_ROOT"))
        env = {**{k: v for k, v in os.environ.items() if not (phone and k in PHONE_SESSION)}, **env}
    env = {k: v for k, v in env.items() if not k.startswith(FOREIGN)}
    user = pwd.getpwuid(os.getuid())
    env.update(HOME=user.pw_dir, USER=user.pw_name, LOGNAME=user.pw_name, SHELL=env.get("SHELL") or user.pw_shell)
    env["XDG_RUNTIME_DIR"] = env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    env.setdefault("TERM", "xterm-256color")
    return env


def tmux(*args, env):
    return subprocess.run(["tmux", "-L", SOCKET, "-f", str(config_file()), *args], env=env, capture_output=True, text=True)


def sessions(agent, env):
    """This agent's sessions, most recently used first."""
    out = tmux("list-sessions", "-F", "#{session_name}\t#{session_activity}", env=env).stdout
    found = [line.split("\t") for line in out.splitlines() if "\t" in line]
    mine = [(name, int(when or 0)) for name, when in found if re.fullmatch(re.escape(agent) + r"(-\d+)?", name)]
    return [name for name, _ in sorted(mine, key=lambda item: -item[1])]


def screen(environ):
    """Which screen a terminal is on: the laptop's display, or one phone's."""
    return environ.get("ADAPTIVE_MOBILE_ROOT", ""), environ.get("DISPLAY", ""), environ.get("WAYLAND_DISPLAY", "")


def shown_here(env):
    """Sessions that already have a terminal on this screen."""
    here = screen(os.environ)
    out = tmux("list-clients", "-F", "#{client_pid}\t#{session_name}", env=env).stdout
    names = set()
    for line in out.splitlines():
        pid, _, name = line.partition("\t")
        try:
            raw = Path(f"/proc/{pid}/environ").read_bytes()
        except OSError:
            continue
        environ = dict(item.split("=", 1) for item in raw.decode(errors="replace").split("\0") if "=" in item)
        if screen(environ) == here:
            names.add(name)
    return names


def project_dir():
    """The active project (project-context), or home."""
    path = Path.home() / ".config/adaptive-desktop/projects.json"
    try:
        data = json.loads(path.read_text())
        folder = Path(data["projects"][data["active_id"]]["path"])
        if folder.is_dir():
            return folder
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return Path.home()


def create(agent, folder, env):
    taken = set(sessions(agent, env))
    name = agent if agent not in taken else next(f"{agent}-{n}" for n in range(2, 1000) if f"{agent}-{n}" not in taken)
    shell = env["SHELL"]
    # A login, interactive shell reads the same files a laptop terminal does,
    # and stays in the folder once the agent exits.
    command = f"{shlex.quote(agent)}; exec {shlex.quote(shell)} -l"
    result = tmux("new-session", "-d", "-s", name, "-c", str(folder), *[f"-e{k}={v}" for k, v in env.items()
                  if k in ("DISPLAY", "XAUTHORITY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS")],
                  "--", shell, "-l", "-i", "-c", command, env=env)
    if result.returncode:
        raise SystemExit(result.stderr.strip() or "tmux could not start the session")
    return name


def choose(agent, new, folder, env):
    if not new and folder is None:
        here = shown_here(env)
        for name in sessions(agent, env):
            if name not in here:
                return name
    return create(agent, folder or project_dir(), env)


def main():
    args = sys.argv[1:]
    if not args or args[0] not in AGENTS or args[0] in ("-h", "--help"):
        raise SystemExit(__doc__.strip())
    agent, rest = args[0], args[1:]
    new = "--new" in rest
    folders = [a for a in rest if a != "--new"]
    folder = Path(folders[0]).expanduser().resolve() if folders else None
    if folder is not None and not folder.is_dir():
        raise SystemExit(f"Not a folder: {folder}")
    if not shutil.which("tmux"):
        raise SystemExit("adaptive-agent needs tmux: sudo apt install tmux")
    env = laptop_env()
    if not shutil.which(agent, path=env["PATH"]) and not shutil.which(agent):
        # The login shell may still find it; say so only if it does not.
        probe = subprocess.run([env["SHELL"], "-l", "-i", "-c", f"command -v {shlex.quote(agent)}"], env=env,
                               capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if probe.returncode:
            raise SystemExit(f"{agent} is not installed for {env['USER']}")
    name = choose(agent, new, folder, env)
    attach = ["tmux", "-L", SOCKET, "-f", str(config_file()), "attach-session", "-t", name]
    here = {k: v for k, v in os.environ.items() if not k.startswith("TMUX")}
    if sys.stdin.isatty() and sys.stdout.isatty() and os.environ.get("ADAPTIVE_AGENT_WINDOW") != "1":
        os.execvpe("tmux", attach, here)
    # Started from a desktop entry: a terminal of its own. exec keeps the
    # process the launcher started, which is how the phone finds its window.
    title = AGENTS[agent] + ("" if name == agent else " " + name.rsplit("-", 1)[1])
    terminal = shutil.which("kterm-terminal") or shutil.which("x-terminal-emulator")
    if not terminal:
        raise SystemExit("adaptive-agent needs a terminal: ./install.sh --only terminal")
    os.execvpe(terminal, [terminal, "--title", title, "-x", *attach], here)


if __name__ == "__main__":
    main()
