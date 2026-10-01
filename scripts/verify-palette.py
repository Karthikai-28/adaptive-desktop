#!/usr/bin/env python3
"""Drive the real Command palette window and check what it lists.

verify-feature-logic.py checks the providers and modes as functions. This
opens the palette itself - the GTK window in apps/adaptive-command/main.py -
types queries into it and reads the rows back, so the wiring between the two
is checked as well: ranking, the worker thread, modes, and Enter.

It runs on a virtual display with its own session bus and HOME, with the
Project Context Service started against that HOME, so it never sees or
changes your registry, snippets or notes.

    scripts/verify-palette.py
"""

import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import sandbox_display  # noqa: E402


def inner(sandbox, check):
    home = Path.home()

    # A project with a repository, a branch, a file to search and an inbox.
    project = home / "code" / "alpha"
    project.mkdir(parents=True)
    git = ["git", "-C", str(project), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run(["git", "-C", str(project), "init", "-q", "-b", "main"], check=True)
    (project / "notes.txt").write_text("the quick brown palette-needle jumps\n")
    subprocess.run(git + ["add", "."], check=True)
    subprocess.run(git + ["commit", "-q", "-m", "first"], check=True)
    subprocess.run(git + ["branch", "feature/login"], check=True)
    (project / "dirty.txt").write_text("x")

    service = subprocess.Popen([sys.executable, str(REPO / "services/project-context/main.py")],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def call(method, *args):
        return subprocess.run(
            ["gdbus", "call", "--session", "-d", "org.adaptive.ProjectContext",
             "-o", "/org/adaptive/ProjectContext", "-m", f"org.adaptive.ProjectContext.{method}", *args],
            capture_output=True, text=True).stdout.strip()

    for _ in range(50):
        if call("ListProjects"):
            break
        time.sleep(0.1)
    pid = call("AddProject", str(project), "Alpha").strip("(),'")
    call("SetActiveProject", pid)

    inbox = home / ".local/share/adaptive-desktop/notes/Alpha/Inbox.md"
    inbox.parent.mkdir(parents=True)
    inbox.write_text("# Alpha inbox\n\n- 2026-10-01 09:00  ship the palette\n")
    commands = home / ".config/adaptive-desktop/commands"
    commands.mkdir(parents=True)
    marker = sandbox / "command-ran"
    script = commands / "touch-marker.sh"
    script.write_text(f"#!/bin/sh\n# title: Touch the marker\ntouch {marker}\n")
    script.chmod(0o700)

    # The project CLI against the same sandboxed service: it is what the
    # palette's "new" mode and the shell's resume call.
    def cli(*args):
        done = subprocess.run([sys.executable, str(REPO / "scripts/project-cli.py"), *args],
                              capture_output=True, text=True, timeout=30)
        return done.returncode, done.stdout + done.stderr

    code, out = cli("startup", "list")
    check(code == 0 and "runs nothing on resume" in out, "cli: startup list on a project with none")
    code, out = cli("startup", "add", "--background", "touch", str(sandbox / "cli-startup"))
    check(code == 0 and "1 command(s)" in out, "cli: startup add")
    code, out = cli("startup", "list")
    check("[background] touch" in out, "cli: startup list shows it")
    cli("startup", "run")
    for _ in range(40):
        if (sandbox / "cli-startup").exists():
            break
        time.sleep(0.1)
    check((sandbox / "cli-startup").exists(), "cli: startup run runs it")
    code, out = cli("startup", "add", "--", "npm", "run", "dev", "--host")
    check(code == 0 and "npm run dev --host" in cli("startup", "list")[1],
          "cli: a command with options of its own goes after --")
    code, out = cli("startup", "clear")
    check(code == 0 and "runs nothing" in cli("startup", "list")[1], "cli: startup clear")
    code, out = cli("git")
    check(code == 0 and "Alpha" in out and "main ±1" in out, "cli: git overview")
    code, out = cli("time")
    check(code == 0, "cli: time report")
    code, out = cli("tasks")
    check(code == 0 and "ship the palette" in out, "cli: tasks lists the inbox")
    code, out = cli("new", str(home / "code" / "beta"), "--template", "python")
    registry = json.loads((home / ".config/adaptive-desktop/projects.json").read_text())["projects"]
    beta = next((v for v in registry.values() if v["name"] == "beta"), None)
    check(code == 0 and (home / "code/beta/src").is_dir() and (home / "code/beta/.git").is_dir(),
          "cli: new creates the folder from the template")
    check(beta is not None and beta["pinned_dirs"] == [str(home / "code/beta/src"), str(home / "code/beta/tests")]
          and beta["metadata"].get("startup"), "cli: new registers it with the template's settings")
    code, out = cli("new", str(home / "code" / "gamma"), "--template", "nope")
    check(code == 1 and not (home / "code/gamma").exists(), "cli: an unknown template creates nothing")

    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import GLib

    sys.path.insert(0, str(REPO / "apps/adaptive-command"))
    import main as palette

    app = palette.CommandApp()
    state = {"window": None}

    def rows():
        return [(r.group, r.title) for r in state["window"].results]

    def titles(group):
        return [title for g, title in rows() if g == group]

    def ask(query, wait_ms=700):
        """Type query and let the debounce and the worker thread finish."""
        window = state["window"]
        window.entry.set_text(query)
        loop = GLib.MainLoop()
        GLib.timeout_add(wait_ms, loop.quit)
        loop.run()

    def enter():
        state["window"]._activate_selected()

    def script_body():
        try:
            run_checks()
        except Exception as error:  # noqa: BLE001 - report it as a failed check
            import traceback
            check(False, f"the check script raised {error!r}: {traceback.format_exc(limit=3)}")
        app.quit()
        return GLib.SOURCE_REMOVE

    def run_checks():
        window = state["window"]
        check(window is not None and window.is_visible(), "the palette window opens")

        ask("")
        check("Open Files" in titles("Actions") and "Alpha" in titles("Projects"),
              "empty field lists actions and projects")
        check("Touch the marker" in titles("Actions"), "your own command is listed as an action")

        ask("12*(3+4)")
        check(rows()[0] == ("Calculator", "= 84"), "a sum is answered first")

        ask("snip")
        check(rows()[0] == ("Snippets", "No snippets yet"), "snip mode: empty state")
        palette.M.add_snippet("Signature", "Regards, K")
        ask("snip sig")
        check(rows()[0] == ("Snippets", "Signature"), "snip mode: finds a saved snippet")

        ask("todo")
        check(rows()[0] == ("Tasks", "ship the palette"), "todo mode: the inbox's open task")
        enter_target = state["window"].results[0]
        enter_target.action()
        check("- [x] 2026-10-01 09:00  ship the palette" in inbox.read_text(), "todo mode: Enter ticks it in the file")
        ask("todo ")
        check(rows()[0] == ("Tasks", "No open tasks"), "todo mode: a ticked task is gone")

        ask("git", 1500)
        check(("Git", "Alpha") in rows(), "git mode: the project is listed (worker thread)")
        git_row = next(r for r in state["window"].results if r.group == "Git" and r.title == "Alpha")
        check(git_row.subtitle.startswith("main ±1"), f"git mode: live status ({git_row.subtitle.split('  ')[0]})")

        ask("/palette-needle", 1500)
        found = [r for r in state["window"].results if r.group == "In Files"]
        check(bool(found) and found[0].subtitle == "notes.txt:1", "grep mode: finds the line in the project")

        ask("branch")
        check(("Branches", "Switch to feature/login") in rows(), "branch mode: the other branch is offered")
        check(("Branches", "Switch to main") not in rows(), "branch mode: the current branch is not")

        ask("time")
        check(rows()[0][0] == "Time", "time mode: answers from the service")

        ask("timer 10m tea")
        check(rows()[0] == ("Timer", "Start a 10 min timer: tea"), "timer mode: parsed")

        ask("keys")
        check(rows()[0][0] == "Shortcuts", "keys mode: lists shortcuts")

        ask("kill zzzz-no-such-process")
        check(rows()[0] == ("Processes", "No process of yours matches"), "kill mode: nothing matching, nothing offered")

        ask("new")
        check("new python <folder>" in titles("New Project"), "new mode: shipped templates listed")

        ask("github")
        check(not any(g == "Git" for g, _ in rows()), "a word that merely starts with a mode is an ordinary search")

        ask("snippets")
        mode_row = next((r for r in state["window"].results if r.title == "Snippets"), None)
        check(mode_row is not None and mode_row.fill == "snip ", "a mode is offered by name")
        if mode_row:
            state["window"]._activate(mode_row)
            check(state["window"].entry.get_text() == "snip " and state["window"].is_visible(),
                  "choosing a mode types its word and keeps the palette open")

        ask("touch the marker")
        command_row = next((r for r in state["window"].results if r.title == "Touch the marker"), None)
        if command_row:
            command_row.action()
        for _ in range(40):
            if marker.exists():
                break
            time.sleep(0.1)
        check(marker.exists(), "Enter on your own command runs it")

    def wait_for_window():
        state["window"] = app.props.active_window
        if state["window"] is None:
            return GLib.SOURCE_CONTINUE
        GLib.timeout_add(600, script_body)
        return GLib.SOURCE_REMOVE

    GLib.timeout_add(100, wait_for_window)
    GLib.timeout_add_seconds(120, app.quit)
    try:
        app.run([])
    finally:
        service.terminate()


if __name__ == "__main__":
    sys.exit(sandbox_display.run(__file__, inner, "Palette window"))
