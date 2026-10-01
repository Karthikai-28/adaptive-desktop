#!/usr/bin/env python3
"""Checks for the palette providers, quick notes, workspace naming and the
phone helper - everything in them that needs no display, shell or phone.

Each is the shipped code: the palette's providers.py and the quick-note
script are imported, and the project service's merge_workspace_names() is
lifted out of services/project-context/main.py with ast, so this runs even
where that module's GNOME imports would not.
"""

import ast
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
failures = []


def check(condition, message):
    print(f"{'OK  ' if condition else 'FAIL'} {message}")
    if not condition:
        failures.append(message)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def lift_function(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    namespace = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


def providers():
    P = load(REPO / "apps/adaptive-command/providers.py", "palette_providers")
    check(P.calculate("12*(3+4)") == "84", "calc: arithmetic")
    check(P.calculate("=2^10") == "1024", "calc: = prefix and ^")
    check(P.calculate("sqrt(2)") == "1.41421356237", "calc: functions")
    check(P.calculate("10 % 3") == "1", "calc: modulo")
    check(P.calculate("0.1+0.2") == "0.3", "calc: float noise trimmed")
    check(P.calculate("42") is None and P.calculate("firefox") is None, "calc: plain words and numbers are not sums")
    check(P.calculate("9**9**9") is None, "calc: runaway exponent refused, not computed")
    check(P.calculate("1/0") is None, "calc: division by zero answers nothing")
    for hostile in ('__import__("os").system("x")', "(1).__class__", "open('f')", "[1]*9", "lambda: 1"):
        check(P.calculate(hostile) is None, f"calc: refuses {hostile}")

    check(P.convert("5 km to mi") == "5 km = 3.10686 mi", "units: length")
    check(P.convert("100 c to f") == "100 c = 212 f", "units: temperature")
    check(P.convert("3 gib in mb") == "3 gib = 3221.23 mb", "units: binary data sizes")
    check(P.convert("2 kg to mi") is None, "units: mismatched dimensions refused")
    check(P.convert("hello") is None, "units: not a conversion")

    check(P.emoji(":rocket") == [("🚀", "Rocket")], "emoji: by name")
    check(P.emoji(":thumbs up")[0][0] == "👍", "emoji: several words")
    check(P.emoji("rocket") == [] and P.emoji(":") == [], "emoji: only with the : prefix")

    check(P.clipboard_query("clip") == "" and P.clipboard_query("cb foo") == "foo", "clipboard: mode prefix")
    check(P.clipboard_query("clipper") is None, "clipboard: a word that starts with clip is not the mode")

    windows = [
        {"id": 1, "title": "README.md - Code", "appName": "Code", "focused": True},
        {"id": 2, "title": "Inbox - Mail", "appName": "Firefox", "focused": False},
        {"id": 3, "title": "readme notes", "appName": "Text Editor", "focused": False},
    ]
    check([w["id"] for w in P.match_windows(windows, "readme")] == [3, 1], "windows: match, focused one last")
    check(P.match_windows(windows, "r") == [], "windows: one letter matches nothing")
    check(P.shell_call("ListWindows") is None, "shell bridge: unreachable shell gives None, not an error")


def quick_note():
    with tempfile.TemporaryDirectory() as home:
        os.environ["HOME"] = home
        Q = load(REPO / "scripts/adaptive-quick-note.py", "quick_note")
        Q.NOTES_DIR = Path(home) / "notes"
        path = Q.inbox_path("My Project!")
        check(path == Path(home) / "notes" / "My_Project_" / "Inbox.md",
              "quick note: same folder naming as the Projects app")
        check(Q.inbox_path("") .parent.name == "General", "quick note: no project goes to General")
        check(Q.append_note(path, "first\nline", now=0), "quick note: saved")
        check(not Q.append_note(path, "   "), "quick note: blank is not saved")
        Q.append_note(path, "second", now=60)
        text = path.read_text(encoding="utf-8")
        check(text.startswith("# My_Project_ inbox"), "quick note: inbox gets a heading once")
        check(text.count("\n- ") == 2 and "first line" in text, "quick note: one line per note")
        check([n.split("  ", 1)[1] for n in Q.recent_notes(path)] == ["first line", "second"],
              "quick note: recent notes, oldest first")


def workspace_names():
    merge = lift_function(REPO / "services/project-context/main.py", "merge_workspace_names")
    names, owned = merge([], {}, {1: "Alpha"})
    check(names == ["", "Alpha"] and owned == {1: "Alpha"}, "names: a project names its workspace")
    names, owned = merge(["Mail", "Alpha"], {1: "Alpha"}, {1: "Alpha Renamed"})
    check(names == ["Mail", "Alpha Renamed"], "names: follows a renamed project, leaves yours")
    names, owned = merge(["Mine", ""], {}, {0: "Alpha"})
    check(names == ["Mine"] and owned == {}, "names: never replaces a name you chose")
    names, owned = merge(["Mail", "Alpha"], {1: "Alpha"}, {})
    check(names == ["Mail"] and owned == {}, "names: released when the project leaves")
    names, owned = merge(["Mail", "Edited"], {1: "Alpha"}, {})
    check(names == ["Mail", "Edited"], "names: a slot you edited is not cleared")


def phone_helper():
    try:
        phone = load(REPO / "shell/adaptive-shell@local/tools/phone_info.py", "phone_info")
    except ImportError:
        print("SKIP phone helper: python gi is not installed here")
        return
    check(phone.main(["x", "ring", "kdeconnect", "../../etc"])["error"] == "bad device",
          "phone: a device id cannot become a path")
    check(phone.main(["x", "send", "other", "abc"])["error"] == "bad device", "phone: unknown backend refused")
    check(phone.main(["x", "explode"])["ok"] is False, "phone: unknown command refused")


def main():
    providers()
    quick_note()
    workspace_names()
    phone_helper()
    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("Feature logic checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
