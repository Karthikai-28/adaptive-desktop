#!/usr/bin/env python3
"""Checks for apps/adaptive-settings that need no display.

The window itself can only be exercised in the session, so this covers what
can be proven without one: both modules compile, every self._method() the
window calls is defined (Python, like GJS, resolves them only when called),
the backend's parsing and safety rules hold, and the Command palette and the
CLIs it reuses still expose what it relies on.

Nothing here writes to gsettings, the project registry or the verification
record; the backend runs against a temporary HOME.
"""

import importlib.util
import os
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
APP = REPO / "apps" / "adaptive-settings"

failures = []


def check(condition, message):
    if condition:
        print(f"OK   {message}")
    else:
        print(f"FAIL {message}")
        failures.append(message)


def load_backend(home):
    os.environ["HOME"] = str(home)
    spec = importlib.util.spec_from_file_location("adaptive_settings_backend", APP / "backend.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    for name in ("main.py", "backend.py"):
        path = APP / name
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
        print(f"OK   {name} compiles")

    source = (APP / "main.py").read_text(encoding="utf-8")
    defined = set(re.findall(r"^\s+def (\w+)\(", source, re.M))
    called = set(re.findall(r"self\.(_\w+)\(", source))
    missing = sorted(called - defined)
    check(not missing, f"every self._method() in main.py is defined {missing or ''}")

    with tempfile.TemporaryDirectory() as home:
        B = load_backend(home)

        check(B.parse_strv("@as []") == [], "parse_strv reads an empty typed array")
        check(B.parse_strv("['a', 'b']") == ["a", "b"], "parse_strv reads a list")
        check(B.parse_strv("garbage") == [], "parse_strv tolerates junk")
        check(B.parse_string("'<Alt>space'") == "<Alt>space", "parse_string unquotes")

        check(B.normalize_accel("<Alt>space") == B.normalize_accel("<Mod1>Space"),
              "accelerator aliases normalize alike")
        check(B.normalize_accel("<Super><Alt>Left") == B.normalize_accel("<Alt><Super>left"),
              "modifier order does not matter")
        check(B.normalize_accel("disabled") == "" and B.normalize_accel("") == "",
              "disabled accelerators normalize to empty")

        grabbed = B.parse_list_recursively(
            "org.gnome.desktop.wm.keybindings switch-to-workspace-left "
            "['<Super>Page_Up', '<Super><Alt>Left']\n"
            "org.gnome.desktop.wm.keybindings close ['<Alt>F4']\n"
            "org.gnome.desktop.wm.keybindings activate-window-menu @as []\n")
        check(len(grabbed) == 3, "list-recursively output parses")
        check(B.find_conflicts("<Alt><Super>left", grabbed)
              == ["org.gnome.desktop.wm.keybindings switch-to-workspace-left"],
              "the Super+Alt+Left trap from the backlog is detected")
        check(B.find_conflicts("<Super><Alt>t", grabbed) == [], "a free shortcut has no conflict")
        check(B.find_conflicts("", grabbed) == [], "clearing a shortcut never conflicts")

        check(B.parse_apt_check("12;3") == (12, 3), "apt-check counts parse")
        check(B.parse_apt_check("") is None, "unreadable apt-check gives None")
        check(B.parse_ahead_behind("0\t4") == (0, 4), "ahead/behind parses")
        check(B.parse_ahead_behind("fatal: no upstream") is None, "no upstream gives None")

        clean = {"upstream": "origin/master", "dirty": 0}
        check(B.update_blocker(clean, (0, 2)) == "", "a clean, behind checkout may update")
        check(B.update_blocker({**clean, "dirty": 1}, (0, 2)) != "", "a dirty checkout may not")
        check(B.update_blocker(clean, (1, 2)) != "", "a diverged checkout may not")
        check(B.update_blocker(clean, (0, 0)) == "Already up to date", "up to date is reported")
        check(B.update_blocker(clean, None) != "", "nothing updates before a check")
        check(B.update_blocker({**clean, "upstream": ""}, (0, 2)) != "",
              "a branch without upstream may not update")
        check(B.update_blocker(None, (0, 2)) != "", "a non-checkout may not update")

        check(B.workspace_choice(-1, 9) == 0 and B.workspace_choice(0, 9) == 1,
              "workspace index maps to dropdown position")
        check(B.workspace_choice(42, 9) == 0 and B.workspace_choice("x", 9) == 0,
              "out-of-range workspace shows None")
        check(B.focus_choice({"metadata": {"focus": "off"}}) == 2
              and B.focus_choice({}) == 0 and B.focus_choice({"metadata": {"focus": "?"}}) == 0,
              "focus preference maps to dropdown position")

        ordered = B.sorted_projects({
            "a": {"id": "a", "name": "Alpha", "last_active_at": 5},
            "b": {"id": "b", "name": "Beta", "last_active_at": 9},
            "c": {"id": "c", "name": "Gamma", "last_active_at": 1},
        }, "c")
        check([p["id"] for p in ordered] == ["c", "b", "a"], "active first, then most recent")

        check(B.describe_age(None) == "never built" and B.describe_age(7200) == "2 hours old",
              "index age reads naturally")
        check(B.home_relative(str(Path(home) / "src")) == "~/src", "paths shown below ~")
        check(B.home_relative(home + "x/src") == home + "x/src",
              "a sibling of home is not mistaken for it")

        check(not B.clamshell_enabled(), "clamshell starts off")
        B.set_clamshell(True)
        check(B.clamshell_enabled(), "clamshell opt-in writes the flag lid-watch reads")
        B.set_clamshell(False)
        B.set_clamshell(False)
        check(not B.clamshell_enabled(), "clamshell opt-out is idempotent")

        check(B.projects_from_file() == ({}, ""), "missing registry reads as empty")

        facts = B.session_facts()
        check("ubuntu_session_entry" in facts, "session-cli.py exposes facts()")
        check(B.recovery_steps() and "gnome-extensions" in B.recovery_steps()[0],
              "session-cli.py exposes RECOVERY_STEPS")
        rows = B.verification()
        check(rows and all("id" in c and "prompt" in c for c, _ in rows),
              "record-live-verification.py exposes its checks")
        recorder = B._load_script("record-live-verification.py")
        check(callable(getattr(recorder, "record_result", None)),
              "record-live-verification.py exposes record_result()")

    palette = (REPO / "apps" / "adaptive-command" / "main.py").read_text(encoding="utf-8")
    check("adaptive-settings-launch.sh" in palette, "the Command palette opens Adaptive Settings")
    sections = set(re.findall(r'"--section", s\]|\("[^"]+", "(projects|search|system)"', palette))
    check({"projects", "search", "system"} <= sections, "the palette lists all three sections")
    launcher = REPO / "scripts" / "adaptive-settings-launch.sh"
    check(launcher.exists() and os.access(launcher, os.X_OK), "launcher is executable")

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("Adaptive Settings checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
