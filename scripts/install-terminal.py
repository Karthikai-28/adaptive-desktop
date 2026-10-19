#!/usr/bin/env python3
"""Configure the installed KTERM as Terminal. Preview by default; --apply installs."""

import argparse
import ast
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess


REPO = Path(__file__).resolve().parent.parent
HOME = Path.home()
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config"))
DATA = Path(os.environ.get("XDG_DATA_HOME", HOME / ".local/share"))
BIN = HOME / ".local/bin"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    profile = CONFIG / "karthi-shell/terminator-modern.conf"
    if not profile.is_file() or not shutil.which("terminator"):
        raise SystemExit("Install KTERM first: terminal/install-kterm-ubuntu.sh")
    backup = REPO / "logs/terminal-setup-before"

    def write(path, content, mode=None):
        content = content.encode() if isinstance(content, str) else content
        if path.is_file() and path.read_bytes() == content:
            return
        print(f"{'Update' if args.apply else 'Would update'} {path}")
        if not args.apply:
            return
        if mode is None:
            mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
        if path.is_file():
            saved = backup / path.relative_to(HOME)
            if not saved.exists():
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, saved)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(mode)

    launcher = (REPO / "terminal/launcher.py").read_bytes()
    for name in ("kterm-terminal", "x-terminal-emulator", "gnome-terminal"):
        write(BIN / name, launcher, 0o755)
    write(CONFIG / "karthi-shell/state/default-mode", "modern\n")
    write(CONFIG / "terminator/config", profile.read_bytes())

    desktop = f'''[Desktop Entry]
Version=1.0
Type=Application
Name=Terminal
GenericName=Terminal
Comment=Open a command line
Exec="{BIN / 'kterm-terminal'}"
Icon=kterm-terminal
Terminal=false
Categories=System;TerminalEmulator;
StartupNotify=true
StartupWMClass=terminator
X-TerminalArgExec=-x
X-TerminalArgDir=--working-directory
X-TerminalArgTitle=--title
Keywords=shell;command;commandline;kterm;terminator;terminal;
Actions=NewWindow;

[Desktop Action NewWindow]
Name=New Window
Exec="{BIN / 'kterm-terminal'}"
Icon=kterm-terminal
'''
    write(DATA / "applications/kterm-terminal.desktop", desktop)
    # Keep legacy desktop IDs launchable, but show only one Terminal in the app grid.
    for name in ("org.gnome.Terminal.desktop", "terminator.desktop", "kterm-classic-terminal.desktop"):
        alias = desktop.replace("StartupWMClass=terminator\n", "NoDisplay=true\n")
        write(DATA / "applications" / name, alias)
    for name in ("xdg-terminals.list", "gnome-xdg-terminals.list", "ubuntu-xdg-terminals.list"):
        path = CONFIG / name
        previous = path.read_text().splitlines() if path.exists() else []
        previous = [line for line in previous if line not in ("kterm-terminal.desktop", "terminator.desktop", "org.gnome.Terminal.desktop")]
        write(path, "\n".join(["kterm-terminal.desktop", *previous]) + "\n")

    dropdown = CONFIG / "adaptive-desktop/dropdown.json"
    options = json.loads(dropdown.read_text()) if dropdown.exists() else {}
    options["terminal"] = "kterm-terminal"
    write(dropdown, json.dumps(options, indent=2) + "\n")

    settings_file = CONFIG / "Antigravity IDE/User/settings.json"
    if settings_file.exists():
        settings = json.loads(settings_file.read_text())
        profiles = settings.setdefault("terminal.integrated.profiles.linux", {})
        profiles["Terminal"] = {"path": "/usr/bin/zsh", "args": ["-l"], "overrideName": True,
                                "icon": "terminal", "env": {"KARTHI_SHELL_MODE": "modern",
                                "KARTHI_MODERN_LOADED": None, "KARTHI_HUD_SHOWN": None}}
        settings.update({"terminal.external.linuxExec": str(BIN / "kterm-terminal"),
                         "terminal.explorerKind": "external",
                         "terminal.integrated.defaultProfile.linux": "Terminal",
                         "terminal.integrated.fontFamily": "JetBrainsMono Nerd Font, monospace",
                         "terminal.integrated.fontSize": 15,
                         "terminal.integrated.cursorStyle": "line",
                         "terminal.integrated.cursorBlinking": True})
        colors = settings.setdefault("workbench.colorCustomizations", {})
        colors.update({"terminal.background": "#11111b", "terminal.foreground": "#cdd6f4",
                       "terminalCursor.foreground": "#f5e0dc"})
        names = ["Black", "Red", "Green", "Yellow", "Blue", "Magenta", "Cyan", "White"]
        palette = ["#45475a", "#f38ba8", "#a6e3a1", "#f9e2af", "#89b4fa", "#f5c2e7", "#94e2d5", "#bac2de",
                   "#585b70", "#f38ba8", "#a6e3a1", "#f9e2af", "#89b4fa", "#f5c2e7", "#94e2d5", "#a6adc8"]
        for i, color in enumerate(palette):
            colors["terminal.ansi" + ("Bright" if i >= 8 else "") + names[i % 8]] = color
        write(settings_file, json.dumps(settings, indent=4) + "\n")

    write(DATA / "nautilus-python/extensions/kterm_open_terminal.py",
          (REPO / "terminal/kterm_open_terminal.py").read_bytes())
    if args.apply:
        subprocess.run(["update-desktop-database", str(DATA / "applications")], check=True)
        # Apply to both this Adaptive session and the normal Ubuntu user profile.
        for profile_name in ("adaptive", "user"):
            env = dict(os.environ, DCONF_PROFILE=profile_name)
            def setting(schema, key, value):
                subprocess.run(["gsettings", "set", schema, key, value], env=env, check=True)
            setting("org.gnome.desktop.default-applications.terminal", "exec", str(BIN / "kterm-terminal"))
            setting("org.gnome.desktop.default-applications.terminal", "exec-arg", "-x")
            media = "org.gnome.settings-daemon.plugins.media-keys"
            shortcut = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/kterm/"
            current = subprocess.check_output(["gsettings", "get", media, "custom-keybindings"], env=env, text=True)
            paths = ast.literal_eval(current.removeprefix("@as ").strip())
            if shortcut not in paths:
                setting(media, "custom-keybindings", repr([*paths, shortcut]))
            schema = media + ".custom-keybinding:" + shortcut
            setting(schema, "name", "Terminal")
            setting(schema, "command", str(BIN / "kterm-terminal"))
            setting(schema, "binding", "<Primary><Alt>t")
            setting(media, "terminal", "[]")
        print("Terminal configured. Existing terminal sessions keep their current shell.")


if __name__ == "__main__":
    main()
