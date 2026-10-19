#!/usr/bin/env python3
"""Check terminal argument transport and ROS setup without opening user windows."""

import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch


REPO = Path(__file__).resolve().parent.parent


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


launcher = load(REPO / "terminal/launcher.py", "terminal_launcher")
ros = load(REPO / "shell/adaptive-shell@local/tools/ros_info.py", "terminal_ros")

with tempfile.TemporaryDirectory(prefix="adaptive-terminal-") as temporary:
    root = Path(temporary)
    # The compatibility launchers must keep argv boundaries, even for shell
    # metacharacters in file paths or a command's arguments.
    folder = "/tmp/project space; echo unwanted"
    payload = ["python3", "-c", "print('one argument')", "$(touch unwanted)"]
    for caller, options in [
        ("kterm-terminal", ["-x", *payload]),
        ("kterm-terminal", ["-e", *payload]),  # Antigravity external tasks
        ("x-terminal-emulator", ["-e", *payload]),
        ("gnome-terminal", ["--wait", "--", *payload]),
    ]:
        assert launcher.terminal_args(["--working-directory", folder, *options], caller) == [
            "--working-directory", folder, "-x", *payload]
    assert launcher.terminal_args(["-e", "printf '%s' 'hello world'"], "gnome-terminal") == [
        "-x", "printf", "%s", "hello world"]
    print("PASS command arguments and folder names survive every launcher alias")

    # Exercise execve itself, including modern-profile selection and clearing
    # inherited shell-init guards so a child gets the complete prompt setup.
    config = root / ".config"
    profile = config / "karthi-shell/terminator-modern.conf"
    profile.parent.mkdir(parents=True)
    profile.write_text("[profiles]\n")
    with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config), "KARTHI_MODERN_LOADED": "1",
                                 "KARTHI_HUD_SHOWN": "1", "KARTHI_SHELL_MODE": "classic"}), \
            patch.object(launcher.shutil, "which", return_value="/usr/bin/terminator"), \
            patch.object(launcher.sys, "argv", ["x-terminal-emulator", "-e", *payload]), \
            patch.object(launcher.os, "execve") as execute:
        launcher.main()
        binary, argv, env = execute.call_args.args
        assert binary == "/usr/bin/terminator"
        assert argv[-len(payload)-1:] == ["-x", *payload]
        assert str(profile) in argv and "--no-dbus" in argv and "modern" in argv
        assert env["KARTHI_SHELL_MODE"] == "modern"
        assert "KARTHI_MODERN_LOADED" not in env and "KARTHI_HUD_SHOWN" not in env
    print("PASS modern profile and fresh KTERM shell initialization")

    # Run the generated ROS Zsh rc file, with a fake distro and an overlay
    # whose path contains spaces. Panel selections must win over .zshrc.
    ros.HOME = root
    ros.CACHE = root / "cache"
    ros.ROS_ROOT = root / "ros"
    distro = ros.ROS_ROOT / "test"
    distro.mkdir(parents=True)
    (distro / "setup.zsh").write_text("export TEST_DISTRO=loaded\n")
    workspace = root / "robot workspace"
    (workspace / "install").mkdir(parents=True)
    (workspace / "install/setup.zsh").write_text("export TEST_OVERLAY=loaded\n")
    (root / ".zshrc").write_text("export TEST_KTERM=loaded ROS_DOMAIN_ID=1 ROS_LOCALHOST_ONLY=1\n")
    setup = dict(distro="test", workspace=str(workspace), domain=88, localhost=False,
                 rmw_set=True, rmw="rmw_test")
    with patch.dict(os.environ):
        os.environ.pop("ZDOTDIR", None)
        rc = ros.terminal_rc(setup)
    result = subprocess.run(["zsh", "-f", "-c", 'source "$1"; print -r -- "$TEST_KTERM|$TEST_DISTRO|$TEST_OVERLAY|$ROS_DOMAIN_ID|${ROS_LOCALHOST_ONLY-unset}|$RMW_IMPLEMENTATION|$PWD|${ZDOTDIR-unset}"',
                             "verify", str(rc)], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == f"loaded|loaded|loaded|88|unset|rmw_test|{workspace}|unset", result
    print("PASS ROS terminal loads Zsh, distro and overlay with the panel's domain and middleware")
    with patch.object(ros.shutil, "which", return_value="/bin/kterm-terminal"), \
            patch.object(ros.subprocess, "Popen") as spawn:
        ros.open_terminal("ROS setup", ["env", "ZDOTDIR=/a b", "zsh", "-i"])
        assert spawn.call_args.args[0] == ["kterm-terminal", "-T", "ROS setup", "-x", "env", "ZDOTDIR=/a b", "zsh", "-i"]
    print("PASS ROS launches Terminal without splitting its environment arguments")

print("All terminal checks passed.")
