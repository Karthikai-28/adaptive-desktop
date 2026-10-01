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
import json
import os
import subprocess
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

    history = [{"id": 3, "text": "newest", "at": 3}, {"id": 9, "kind": "image", "text": "", "size": 348160,
                                                      "width": 1920, "height": 1200, "at": 2},
               {"id": 1, "text": "old but pinned", "at": 1, "pinned": True}]
    entries = P.clipboard_entries(history, "")
    check([e["id"] for e in entries] == [1, 3, 9], "clipboard: pinned first, then newest first")
    check(entries[2]["title"] == "Image" and entries[2]["detail"] == "1920×1200  ·  340 KB", "clipboard: an image says its size")
    check([e["id"] for e in P.clipboard_entries(history, "new")] == [3], "clipboard: a filter matches text, not images")
    check([e["id"] for e in P.clipboard_entries(history, "image")] == [9], "clipboard: \"image\" finds the images")

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
    check(phone.main(["x", "clipboard", "kdeconnect", "a/b"])["error"] == "bad device",
          "phone: clipboard to a bad device id refused")
    listing = {"backend": "gsconnect", "devices": [{"id": "a", "name": "Old", "reachable": False},
                                                    {"id": "b", "name": "Pixel", "reachable": True}]}
    check(phone.first_reachable(listing) == ("gsconnect", "b", "Pixel"), "phone: the first phone in reach is chosen")
    check(phone.first_reachable({"backend": None, "devices": []}) is None, "phone: no phone, no target")
    check(phone.describe({"ok": True, "name": "Pixel"}) == "Clipboard sent to Pixel"
          and phone.describe({"ok": False, "error": "no phone in reach"}) == "No paired phone is in reach",
          "phone: the notification says what happened")


def project_extras():
    E = load(REPO / "services/project-context/extras.py", "project_extras")

    status = E.parse_git_status("## main...origin/main [ahead 1, behind 2]\n M a.js\n?? b\n")
    check(status == {"branch": "main", "ahead": 1, "behind": 2, "dirty": 2, "detached": False},
          "git: branch, ahead, behind, dirty")
    check(E.format_git_status(status) == "main ±2 ↑1 ↓2", "git: same text as the top bar")
    check(E.parse_git_status("fatal: not a git repository") is None, "git: not a repository gives None")
    fake = {"/a": E.parse_git_status("## main\n"), "/b": E.parse_git_status("## dev\n M x\n M y\n"),
            "/c": None, "/d": E.parse_git_status("## main...o/main [ahead 3]\n")}
    rows = E.git_overview({"1": {"name": "Alpha", "path": "/a"}, "2": {"name": "Beta", "path": "/b"},
                           "3": {"name": "Gamma", "path": "/c"}, "4": {"name": "Delta", "path": "/d"}},
                          status_of=lambda path: fake[path])
    check([r["name"] for r in rows] == ["Beta", "Delta", "Alpha", "Gamma"],
          "git overview: work to do first, most uncommitted at the top")
    check(rows[3]["text"] == "not a git repository" and not rows[3]["attention"],
          "git overview: a plain folder is listed, not flagged")

    with tempfile.TemporaryDirectory() as folder:
        subprocess.run(["git", "-C", folder, "init", "-q", "-b", "main"], check=True)
        Path(folder, "new.txt").write_text("x")
        real = E.git_status(folder)
        check(real and real["branch"] == "main" and real["dirty"] == 1, "git: a real repository is read")
        check(E.git_status(folder + "/missing") is None, "git: a missing folder gives None")

    check(E.should_count("p", 1000, False), "time: active, present and unlocked counts")
    check(not E.should_count("", 1000, False), "time: no active project counts nothing")
    check(not E.should_count("p", E.TIME_IDLE_LIMIT_S * 1000, False), "time: idle past the limit does not count")
    check(not E.should_count("p", 0, True), "time: a locked screen does not count")
    data = {"days": {}}
    E.add_time(data, "2026-10-01", "p", 60)
    E.add_time(data, "2026-10-01", "p", 60)
    E.add_time(data, "2026-09-28", "p", 600)
    E.add_time(data, "2026-09-20", "q", 999)
    check(E.summarize_time(data, 1, "2026-10-01") == {"p": 120}, "time: today's total")
    check(E.summarize_time(data, 7, "2026-10-01") == {"p": 720}, "time: seven days, older days left out")
    report = E.time_report(data, {"p": {"name": "Alpha"}}, "2026-10-01")
    check(report == [{"id": "p", "name": "Alpha", "today": 120, "week": 720}], "time: report rows")
    check(E.format_duration(59) == "0 min" and E.format_duration(7500) == "2 h 05 min", "time: durations read naturally")
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "time.json"
        E.save_time(data, path)
        check(E.load_time(path) == data, "time: saved and loaded")
        path.write_text("not json")
        check(E.load_time(path) == {"days": {}}, "time: a corrupt file is an empty record")
    big = {"days": {}}
    for offset in range(E.TIME_KEEP_DAYS + 20):
        E.add_time(big, f"d{offset:05d}", "p", 1)
    check(len(big["days"]) == E.TIME_KEEP_DAYS, "time: very old days are dropped")

    check(E.normalize_startup("make dev") == [{"command": "make dev", "terminal": True}],
          "startup: a plain string is one terminal command")
    check(E.normalize_startup([{"command": " "}, 7, {"command": "x", "terminal": False}]) ==
          [{"command": "x", "terminal": False}], "startup: junk and blanks dropped")
    check(len(E.normalize_startup(["c"] * 30)) == E.STARTUP_LIMIT, "startup: bounded")
    argv = E.startup_argv({"command": "npm run dev", "terminal": True}, "/p")
    check(argv[:2] == ["gnome-terminal", "--working-directory=/p"] and argv[-1] == "npm run dev; exec bash",
          "startup: terminal commands stay open in the project folder")
    check(E.startup_argv({"command": "x", "terminal": False}, "/p") == ["bash", "-lc", "x"],
          "startup: background commands get no window")

    inbox = "# Alpha inbox\n\n- 2026-10-01 09:00  write tests\n- [x] 2026-10-01 09:05  done one\n- bare note\n"
    tasks = E.parse_tasks(inbox)
    check([(t["text"], t["done"]) for t in tasks] ==
          [("write tests", False), ("done one", True), ("bare note", False)], "tasks: inbox lines are tasks")
    check(tasks[0]["stamp"] == "2026-10-01 09:00" and tasks[2]["stamp"] == "", "tasks: the note's time is kept")
    ticked = E.set_task_done(inbox, tasks[0]["line"])
    check("- [x] 2026-10-01 09:00  write tests" in ticked, "tasks: ticking keeps the time and text")
    check(E.set_task_done(ticked, tasks[0]["line"], done=False) == inbox, "tasks: unticking restores the line")
    check(E.set_task_done(inbox, 0) == inbox and E.set_task_done(inbox, 99) == inbox,
          "tasks: a line that is not a task is never rewritten")

    with tempfile.TemporaryDirectory() as folder:
        templates_dir = Path(folder) / "templates"
        templates_dir.mkdir()
        (templates_dir / "py.json").write_text(json.dumps({
            "folders": ["src", "../escape", "/abs"], "files": {"README.md": "# {name}\n", "../x": "no"},
            "pinned": ["src", "../.."], "focus": "on", "startup": ["make"]}))
        (templates_dir / "bad name!.json").write_text("{}")
        (templates_dir / "broken.json").write_text("{")
        templates = E.load_templates([templates_dir, Path(folder) / "absent"])
        check(list(templates) == ["py"], "templates: only well-named, readable ones load")
        root = Path(folder) / "proj"
        (root).mkdir()
        (root / "README.md").write_text("mine")
        created, patch = E.apply_template(templates["py"], root)
        check((root / "src").is_dir() and not (Path(folder) / "escape").exists() and not Path(folder, "x").exists(),
              "templates: nothing is created outside the project")
        check((root / "README.md").read_text() == "mine", "templates: an existing file is never overwritten")
        check(patch == {"pinned_dirs": [str(root / "src")],
                        "metadata": {"focus": "on", "startup": [{"command": "make", "terminal": True}]}},
              "templates: pinned folders, focus and startup go to the registry")
        shipped = E.load_templates([REPO / "config" / "project-templates"])
        check({"python", "web", "writing"} <= set(shipped), "templates: the shipped ones load")


def palette_modes():
    M = load(REPO / "apps/adaptive-command/modes.py", "palette_modes")

    check(M.mode_of("git") == ("git", "") and M.mode_of("snip save Sig") == ("snip", "save Sig"), "modes: word then rest")
    check(M.mode_of("github") == (None, "") and M.mode_of("timeline") == (None, ""),
          "modes: a longer word is an ordinary search")
    check(M.mode_of("/needle here") == ("grep", "needle here") and M.mode_of("/") == (None, ""), "modes: / is grep")

    with tempfile.TemporaryDirectory() as folder:
        snippets = Path(folder) / "snippets.json"
        check(M.add_snippet("Sig", "Regards,\nK", snippets) == "", "snippets: saved")
        check(M.add_snippet("../x", "t", snippets) != "" and M.add_snippet("ok", "  ", snippets) != "",
              "snippets: bad names and empty text refused")
        check(oct(snippets.stat().st_mode & 0o777) == "0o600", "snippets: the file is private")
        rows = M.snippet_rows("", snippets)
        check(rows[0]["title"] == "Sig" and rows[0]["action"] == ("copy", "Regards,\nK"), "snippets: Enter copies")
        check(M.snippet_rows("regards", snippets)[0]["title"] == "Sig", "snippets: found by their text")
        check(M.snippet_rows("save New", snippets)[0]["action"] == ("snippet-save", "New"), "snippets: save row")
        check(M.snippet_rows("rm si", snippets)[0]["action"] == ("snippet-delete", "Sig"), "snippets: delete row")
        check(M.delete_snippet("Sig", snippets) and not M.delete_snippet("Sig", snippets), "snippets: deleted once")
        check(M.snippet_rows("", snippets)[0]["action"] is None, "snippets: empty state has no action")

        notes = Path(folder) / "notes"
        inbox = M.extras.tasks_path("Alpha", notes)
        inbox.parent.mkdir(parents=True)
        inbox.write_text("# Alpha inbox\n\n- 2026-10-01 09:00  first\n- 2026-10-01 09:05  second\n")
        rows = M.task_rows("", "Alpha", notes)
        check([r["title"] for r in rows] == ["second", "first"], "tasks: open tasks, newest first")
        check(M.complete_task(*rows[0]["action"][1:]) and "- [x] 2026-10-01 09:05  second" in inbox.read_text(),
              "tasks: Enter ticks the task in the inbox")
        check([r["title"] for r in M.task_rows("", "Alpha", notes)] == ["first"], "tasks: a ticked task leaves the list")
        check(M.task_rows("", "Nobody", notes)[0]["action"] is None, "tasks: no inbox is an empty list")

        project = Path(folder) / "code"
        project.mkdir()
        (project / "a:b.txt").write_text("one\nneedle in a haystack\n")
        (project / "c.py").write_text("x = 1  # needle\nneedle\nneedle\nneedle\n")
        hits = M.content_search(project, "needle")
        check(any(h[0].endswith("a:b.txt") and h[1] == 2 for h in hits), "grep: a file name with a colon is read right")
        rows = M.content_rows(hits, project)
        check(sum(1 for r in rows if r["subtitle"].startswith("c.py")) == 2, "grep: at most two lines per file")
        check(rows[0]["action"][0] == "open" and isinstance(rows[0]["action"][2], int), "grep: Enter opens at the line")
        check(M.content_search(project, "ne") == [], "grep: too short a search does not run")

        commands = Path(folder) / "commands"
        commands.mkdir()
        good = commands / "deploy-site.sh"
        good.write_text("#!/bin/sh\n# title: Deploy the site\n# description: rsync to the server\n")
        good.chmod(0o700)
        (commands / "plain").write_text("#!/bin/sh\n")
        (commands / "plain").chmod(0o700)
        loose = commands / "loose.sh"
        loose.write_text("#!/bin/sh\n")
        loose.chmod(0o777)
        (commands / "notexec.sh").write_text("#!/bin/sh\n")
        found = M.user_commands(commands)
        check([c["title"] for c in found] == ["Deploy the site", "Plain"], "commands: titled by header or file name")
        check(found[0]["description"] == "rsync to the server", "commands: description from the header")
        check(all("loose" not in c["path"] and "notexec" not in c["path"] for c in found),
              "commands: world-writable and non-executable files are not offered")

    rows = M.git_rows({"1": {"name": "A", "path": "/a"}},
                      status_of=lambda p: M.extras.parse_git_status("## main\n M f\n"))
    check(rows[0]["subtitle"].startswith("main ±1") and rows[0]["action"][0] == "run", "git mode: status and a terminal")
    check(M.time_rows(None)[0]["action"] is None and "unavailable" in M.time_rows(None)[0]["title"],
          "time mode: service down is said plainly")
    check("1 h 00 min today" in M.time_rows([{"name": "A", "today": 3600, "week": 7200}])[0]["subtitle"], "time mode: rows")

    processes = [{"pid": 10, "name": "firefox", "cmdline": "/usr/lib/firefox/firefox", "start": "5"},
                 {"pid": 11, "name": "gnome-shell", "cmdline": "/usr/bin/gnome-shell", "start": "6"},
                 {"pid": 12, "name": "python3", "cmdline": "python3 palette", "start": "7"}]
    rows = M.process_rows("fire", processes, own_pid=12)
    check(rows[0]["action"] == ("signal", 10, "5"), "kill: matches by name, carries the start time")
    check(M.process_rows("gnome", processes, own_pid=12)[0]["action"] is None, "kill: session processes are never offered")
    check(M.process_rows("python", processes, own_pid=12)[0]["action"] is None, "kill: the palette never offers itself")
    child = subprocess.Popen(["sleep", "60"])
    mine = next(p for p in M.list_processes() if p["pid"] == child.pid)
    check(mine["name"] == "sleep", "kill: this user's processes are listed")
    check(not M.end_process(child.pid, "0"), "kill: a reused pid (different start time) is left alone")
    check(M.end_process(child.pid, mine["start"]) and child.wait(timeout=5) == -15, "kill: asks with SIGTERM")

    hosts = M.parse_ssh_hosts("Host web db-1\n  HostName 10.0.0.1\nHost *\nHost -oProxyCommand=x\nhost Pi\n")
    check(hosts == ["web", "db-1", "Pi"], "ssh: aliases only, no patterns, nothing option-like")
    check(M.ssh_rows("pi", hosts)[0]["action"] == ("run", ["gnome-terminal", "--", "ssh", "Pi"], None), "ssh: opens a terminal")

    rows = M.branch_rows("fe", "/p", ["main", "feature/x"], "main")
    check(rows[0]["action"][2] == ["git", "-C", "/p", "switch", "--", "feature/x"], "branch: switch, never a shell string")
    check(M.branch_rows("", "", [], "")[0]["action"] is None, "branch: no project, no action")
    check(M.branch_rows("main", "/p", ["main"], "main")[0]["action"] is None, "branch: the current branch is not offered")

    check(M.parse_timer("10m tea") == (600, "tea") and M.parse_timer("90s") == (90, ""), "timer: minutes and seconds")
    check(M.parse_timer("1.5h review") == (5400, "review") and M.parse_timer("5") == (300, ""), "timer: hours; a bare number is minutes")
    check(M.parse_timer("0") is None and M.parse_timer("48h") is None and M.parse_timer("soon") is None,
          "timer: zero, over a day and words refused")
    argv = M.timer_argv(600, "tea", now=1)
    check(argv[:2] == ["systemd-run", "--user"] and "--on-active=600" in argv and argv[-1] == "tea",
          "timer: a systemd user timer that outlives the palette")

    check(M.format_accelerator("<Super><Alt>n") == "Super+Alt+N" and M.format_accelerator("<Alt>space") == "Alt+Space",
          "keys: accelerators read the way they are pressed")
    rows = M.shortcut_rows("note", [("Quick Note", "<Super><Alt>n"), ("Command", "<Alt>space"), ("Unset", "")])
    check([r["title"] for r in rows] == ["Quick Note"] and rows[0]["badge"] == "Super+Alt+N", "keys: filtered, unset ones hidden")

    templates = {"python": {"description": "Py"}}
    check(M.new_project_rows("", templates)[0]["title"] == "new python <folder>", "new: templates listed")
    rows = M.new_project_rows("python ~/code/thing", templates)
    check(rows[0]["action"][0] == "run-notify" and rows[0]["action"][2][1:3] == ["new", os.path.expanduser("~/code/thing")],
          "new: creates through project-cli")
    check(M.new_project_rows("rust ~/x", templates)[0]["action"] is None, "new: unknown template refused")

    R = load(REPO / "scripts/adaptive-run-notify.py", "run_notify")
    check(R.summarize(0, "a\nSwitched to branch 'x'\n") == (True, "Switched to branch 'x'"), "run-notify: success shows the last line")
    check(R.summarize(1, "") == (False, "Exited with status 1"), "run-notify: a silent failure still says so")


def annotate_shapes():
    S = load(REPO / "apps/adaptive-annotate/shapes.py", "annotate_shapes")
    shape = S.new_shape("rect", S.COLORS["red"], (10, 10))
    S.extend(shape, (5, 30))
    check(S.bounds(shape) == (5, 10, 5, 20), "annotate: a box dragged backwards is still a box")
    check(S.is_worth_keeping(shape), "annotate: a real drag is kept")
    check(not S.is_worth_keeping(S.extend(S.new_shape("arrow", (1, 0, 0), (0, 0)), (1, 1))), "annotate: a tiny drag is dropped")
    pen = S.new_shape("pen", (1, 0, 0), (0, 0))
    for point in ((1, 1), (2, 3), (4, 4)):
        S.extend(pen, point)
    check(len(pen["points"]) == 5 and S.is_worth_keeping(pen), "annotate: the pen keeps every point")
    check(not S.is_worth_keeping(S.new_shape("text", (1, 0, 0), (0, 0), text="  ")), "annotate: blank text is dropped")
    try:
        S.new_shape("laser", (1, 0, 0), (0, 0))
        check(False, "annotate: an unknown tool is refused")
    except ValueError:
        check(True, "annotate: an unknown tool is refused")
    check(S.fit(400, 300, 800, 600) == (1.0, 200.0, 150.0), "annotate: a small picture is centred, not enlarged")
    scale, x, y = S.fit(4000, 2000, 1000, 1000)
    check((scale, x, y) == (0.25, 0.0, 250.0), "annotate: a large picture is scaled to fit")
    check(S.to_image((500, 500), 0.25, 0.0, 250.0, 4000, 2000) == (2000.0, 1000.0), "annotate: pointer to picture coordinates")
    check(S.to_image((-50, 9999), 0.25, 0.0, 250.0, 4000, 2000) == (0, 2000), "annotate: a drag past the edge stays on the picture")
    try:
        import cairo
    except ImportError:
        print("SKIP annotate rendering: pycairo is not installed here")
        return
    base = cairo.ImageSurface(cairo.FORMAT_ARGB32, 60, 40)
    ctx = cairo.Context(base)
    ctx.set_source_rgb(1, 1, 1)
    ctx.paint()
    redact = S.extend(S.new_shape("redact", S.COLORS["red"], (10, 10)), (30, 30))
    out = S.flatten(base, [redact])
    data, stride = out.get_data(), out.get_stride()
    inside = bytes(data[20 * stride + 20 * 4:20 * stride + 20 * 4 + 3])
    outside = bytes(data[5 * stride + 50 * 4:5 * stride + 50 * 4 + 3])
    check(inside == b"\x00\x00\x00" and outside == b"\xff\xff\xff", "annotate: a redaction is solid, the rest untouched")
    check(bytes(base.get_data()[20 * base.get_stride() + 80:20 * base.get_stride() + 83]) == b"\xff\xff\xff",
          "annotate: the original picture is never drawn on")


def power_auto():
    A = load(REPO / "scripts/adaptive-power-auto.py", "power_auto")
    offered = ["power-saver", "balanced"]
    on = {"auto_profile": True, "battery": "power-saver", "ac": "balanced"}
    check(A.wanted_profile(True, on, offered) == "power-saver" and A.wanted_profile(False, on, offered) == "balanced",
          "power: battery and mains each get their profile")
    check(A.wanted_profile(True, dict(on, auto_profile=False), offered) is None, "power: off means nothing changes")
    check(A.wanted_profile(False, dict(on, ac="performance"), offered) is None,
          "power: a profile this machine lacks is not replaced by another")
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "power.json"
        check(A.load_config(path) == A.DEFAULTS and A.DEFAULTS["auto_profile"] is False, "power: off by default")
        path.write_text('{"auto_profile": "yes", "battery": "turbo", "ac": "performance"}')
        config = A.load_config(path)
        check(config == {"auto_profile": False, "battery": "power-saver", "ac": "performance"},
              "power: junk settings fall back, valid ones are kept")
        A.save_config(dict(config, auto_profile=True), path)
        check(A.load_config(path)["auto_profile"] is True, "power: saved and loaded")


def settings_backup():
    B = load(REPO / "scripts/adaptive-backup.py", "adaptive_backup")

    dump = "\n".join([
        "[org/gnome/desktop/interface]", "gtk-theme='Adaptive'", "",
        "[org/gnome/evolution-data-server/calendar]", "reminders-past=['x a@b.example']", "",
        "[org/gnome/desktop/thumbnailers]", "disable-all=false", "",
        "[org/gnome/online-accounts]", "whitelisted-providers=['google']", "",
        "[org/gnome/shell]", "favorite-apps=['firefox.desktop']", "owner='someone@company.example'",
        "enabled-extensions=['gsconnect@andyholmes.github.io']",
        "blob='" + "x" * 5000 + "'", "",
        "[org/gnome/only-private]", "contact='me@home.example'", ""])
    clean, report = B.redact_dconf(dump)
    check("evolution" not in clean and "online-accounts" not in clean, "backup: account and calendar sections removed")
    check("example" not in clean, "backup: no email address survives, wherever it was")
    check("gsconnect@andyholmes.github.io" in clean, "backup: extension ids are not mistaken for addresses")
    check("blob=" not in clean, "backup: an oversized value is removed")
    check("gtk-theme='Adaptive'" in clean and "favorite-apps" in clean and "thumbnailers" in clean,
          "backup: ordinary settings are kept (thumbnailers is not 'mail')")
    check("[org/gnome/only-private]" not in clean, "backup: a section left empty is dropped")
    check(report == {"sections": 2, "values": 3}, f"backup: what was removed is counted {report}")

    check(B.filter_keys("[/]\nworkspace-names=['a']\nbutton-layout='x'\n\n[sub]\nworkspace-names=['no']\n",
                        ("workspace-names",)) == "[/]\nworkspace-names=['a']\n", "backup: only the named keys of a folder")
    check(B.filter_keys("[/]\nother=1\n", ("workspace-names",)) == "", "backup: nothing to carry gives nothing")
    shortcuts = "[adaptive-command]\nbinding='<Alt>space'\n\n[custom0]\nbinding='<Super>t'\ncommand='mine'\n"
    check(B.filter_adaptive_shortcuts(shortcuts) == "[adaptive-command]\nbinding='<Alt>space'\n\n",
          "backup: only Adaptive's shortcuts, not your other custom ones")

    with tempfile.TemporaryDirectory() as folder:
        folder = Path(folder)
        config, notes = folder / "config", folder / "notes"
        (config / "commands").mkdir(parents=True)
        (config / "snapshots").mkdir()
        (config / "projects.json").write_text('{"projects": {}}')
        (config / "commands" / "go.sh").write_text("#!/bin/sh\n")
        (config / "snapshots" / "p.json").write_text("{}")
        (config / "last-v1.6-backup").write_text("x")
        (config / "session-state.json").write_text("{}")
        (notes / "Alpha").mkdir(parents=True)
        (notes / "Alpha" / "Inbox.md").write_text("- note\n")
        check([str(f) for f in B.config_files(config)] == ["commands/go.sh", "projects.json"],
              "backup: settings are carried, machine history and parked windows are not")

        fake = {"/org/gnome/shell/": "[/]\nfavorite-apps=['a.desktop']\nenabled-extensions=['x']\n",
                B.CUSTOM_KEYS_DIR: shortcuts}
        loaded = []

        def fake_dconf(*args, stdin=None):
            if args[0] == "dump":
                return True, fake.get(args[1], "")
            loaded.append((args[1], stdin))
            return True, ""

        archive = folder / "out.tar.gz"
        manifest = B.export(archive, notes=True, config_dir=config, notes_dir=notes, dump=fake_dconf)
        check(manifest["config"] == ["commands/go.sh", "projects.json"] and manifest["notes"] == ["Alpha/Inbox.md"]
              and manifest["dconf"] == ["/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/",
                                        "/org/gnome/shell/"], "backup: export lists what it holds")
        check(oct(archive.stat().st_mode & 0o777) == "0o600", "backup: the archive is private")

        new_config, new_notes = folder / "new-config", folder / "new-notes"
        new_config.mkdir()
        (new_config / "projects.json").write_text('{"projects": {"old": 1}}')
        plan = B.restore(archive, dry_run=True, config_dir=new_config, notes_dir=new_notes, load=fake_dconf)
        check(any("would write" in line for line in plan) and not loaded
              and (new_config / "projects.json").read_text() == '{"projects": {"old": 1}}',
              "backup: a dry run changes nothing")
        B.restore(archive, config_dir=new_config, notes_dir=new_notes, load=fake_dconf)
        check((new_config / "projects.json").read_text() == '{"projects": {}}', "backup: import restores the files")
        check(oct((new_config / "commands" / "go.sh").stat().st_mode & 0o777) == "0o700",
              "backup: your commands come back runnable")
        kept = list(folder.glob("new-config.before-import-*"))
        check(len(kept) == 1 and (kept[0] / "projects.json").read_text() == '{"projects": {"old": 1}}',
              "backup: what import replaced is kept beside it")
        check((new_notes / "Alpha" / "Inbox.md").exists(), "backup: notes are restored")
        check(("/org/gnome/shell/", "[/]\nfavorite-apps=['a.desktop']\n") in loaded,
              "backup: GNOME settings are loaded back, only the keys that were carried")
        check(B.restore(archive, config_dir=new_config, notes_dir=new_notes, load=fake_dconf)[0].startswith("left "),
              "backup: importing twice overwrites nothing")

        import tarfile as _tar
        evil = folder / "evil.tar.gz"
        with _tar.open(evil, "w:gz") as handle:
            info = _tar.TarInfo("config/../../escape.txt")
            info.size = 1
            handle.addfile(info, __import__("io").BytesIO(b"x"))
        try:
            B.read_archive(evil)
            check(False, "backup: an archive that reaches outside is refused")
        except ValueError:
            check(True, "backup: an archive that reaches outside is refused")


def main():
    providers()
    quick_note()
    workspace_names()
    phone_helper()
    project_extras()
    palette_modes()
    annotate_shapes()
    power_auto()
    settings_backup()
    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("Feature logic checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
