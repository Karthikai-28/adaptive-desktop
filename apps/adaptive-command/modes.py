"""Command palette modes - a word in front of the query that asks for one thing.

    snip [text]            saved snippets; "snip save <name>" keeps the clipboard,
                           "snip rm <name>" forgets one
    todo [text]            the project's quick-note inbox as tasks; Enter ticks one
    git                    every project's branch and uncommitted / unpushed work
    time                   time per project, today and this week
    /text  or  grep text   search inside the active project's files
    kill <name>            end one of your processes (asks it to quit: SIGTERM)
    ssh [host]             hosts from ~/.ssh/config, opened in a terminal
    branch [name]          switch the active project's git branch
    timer 10m [label]      a notification after that long
    keys [text]            every Adaptive keyboard shortcut
    new <template> <path>  a project from a template

Your own commands are executables in ~/.config/adaptive-desktop/commands/;
each shows up as an action, named after its file.

Like providers.py this module has no GTK in it. A mode returns rows as plain
dicts whose "action" is a small tuple the palette knows how to perform, so
scripts/verify-feature-logic.py can check every mode without a display:

    ("copy", text)                      put text on the clipboard
    ("run", argv, cwd)                  start a program
    ("run-notify", title, argv, cwd)    run it and report how it went
    ("open", path, line)                open a file (at a line, if known)
    ("signal", pid, start_ticks)        ask a process to quit
    ("task-done", inbox_path, line)     tick a task
    ("snippet-save", name)              keep the clipboard as a snippet
    ("snippet-delete", name)
    ("timer", seconds, label)
"""

import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "adaptive-desktop"
SNIPPETS_FILE = CONFIG_DIR / "snippets.json"
COMMANDS_DIR = CONFIG_DIR / "commands"

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "services" / "project-context"))
import extras  # noqa: E402

MODE_WORDS = ("snip", "todo", "git", "time", "grep", "kill", "ssh", "branch", "timer", "keys", "new")
_MODE = re.compile(r"^\s*(" + "|".join(MODE_WORDS) + r")(?:\s+(.*))?$", re.I | re.S)


def mode_of(query):
    """(mode, rest) for a query that starts with a mode word, else (None, "").

    The word has to stand alone: "git" and "git status" are the git mode,
    "github" is an ordinary search. "/text" is shorthand for "grep text".
    """
    text = query or ""
    if text.lstrip().startswith("/") and len(text.strip()) > 1:
        return "grep", text.strip()[1:].strip()
    match = _MODE.match(text)
    if not match:
        return None, ""
    return match.group(1).lower(), (match.group(2) or "").strip()


def row(title, subtitle, group, icon, badge="", action=None, score=0):
    return {"title": title, "subtitle": subtitle, "group": group, "icon": icon,
            "badge": badge, "action": action, "score": score}


def _fold(text):
    return " ".join((text or "").split())


def _clip(text, length=110):
    text = _fold(text)
    return text[:length] + ("…" if len(text) > length else "")


# ----------------------------------------------------------------- snippets

SNIPPET_LIMIT = 200
SNIPPET_MAX_CHARS = 20000
_SNIPPET_NAME = re.compile(r"^[\w][\w .-]{0,48}$")


def load_snippets(path=None):
    """{name: text}; an unreadable or malformed file is no snippets."""
    try:
        data = json.loads((path or SNIPPETS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): v for k, v in data.items() if isinstance(v, str)}


def save_snippets(snippets, path=None):
    path = path or SNIPPETS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(snippets, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    # Snippets are whatever you chose to keep; keep them to yourself.
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def add_snippet(name, text, path=None):
    """Save text under name. Returns an error message, or "" when saved."""
    name = _fold(name)
    if not _SNIPPET_NAME.match(name):
        return "A snippet name is letters, digits, spaces, dots and dashes (up to 49)"
    if not isinstance(text, str) or not text.strip():
        return "There is nothing on the clipboard to save"
    if len(text) > SNIPPET_MAX_CHARS:
        return "That is too long to keep as a snippet"
    snippets = load_snippets(path)
    if name not in snippets and len(snippets) >= SNIPPET_LIMIT:
        return f"There are already {SNIPPET_LIMIT} snippets"
    snippets[name] = text
    save_snippets(snippets, path)
    return ""


def delete_snippet(name, path=None):
    snippets = load_snippets(path)
    if _fold(name) not in snippets:
        return False
    del snippets[_fold(name)]
    save_snippets(snippets, path)
    return True


def snippet_rows(rest, path=None):
    snippets = load_snippets(path)
    words = rest.split(None, 1)
    verb = words[0].lower() if words else ""
    argument = words[1].strip() if len(words) > 1 else ""

    if verb == "save":
        if not argument:
            return [row("Save the clipboard as a snippet", "Type a name: snip save <name>",
                        "Snippets", "document-save-symbolic", score=300)]
        replacing = " (replaces the one saved)" if _fold(argument) in snippets else ""
        return [row(f"Save the clipboard as “{_fold(argument)}”", f"Enter saves it{replacing}",
                    "Snippets", "document-save-symbolic", "Save", ("snippet-save", argument), 300)]
    if verb in ("rm", "delete", "remove"):
        hits = [name for name in sorted(snippets, key=str.casefold)
                if argument.casefold() in name.casefold()]
        if not hits:
            return [row("No snippet by that name", "snip rm <name>", "Snippets",
                        "edit-delete-symbolic", score=300)]
        return [row(f"Delete “{name}”", _clip(snippets[name]), "Snippets", "edit-delete-symbolic",
                    "Delete", ("snippet-delete", name), 300 - rank)
                for rank, name in enumerate(hits[:10])]

    folded = rest.casefold()
    hits = [(name, text) for name, text in sorted(snippets.items(), key=lambda kv: kv[0].casefold())
            if folded in name.casefold() or folded in text.casefold()]
    if not hits:
        hint = "Copy something, then: snip save <name>" if not snippets else "No snippet matches"
        return [row("No snippets yet" if not snippets else "No snippet matches", hint,
                    "Snippets", "edit-paste-symbolic", score=300)]
    return [row(name, _clip(text), "Snippets", "edit-paste-symbolic", "Copy", ("copy", text), 300 - rank)
            for rank, (name, text) in enumerate(hits[:12])]


# -------------------------------------------------------------------- tasks

def task_rows(rest, project_name, notes_dir=None):
    path = extras.tasks_path(project_name, notes_dir)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    where = f"{project_name or 'General'} inbox"
    open_tasks = [t for t in extras.parse_tasks(text) if not t["done"]]
    folded = rest.casefold()
    hits = [t for t in open_tasks if folded in t["text"].casefold()]
    if not hits:
        return [row("No open tasks" if not open_tasks else "No task matches",
                    f"{where} · Quick Note (Super+Alt+N) adds one",
                    "Tasks", "checkbox-checked-symbolic", score=300)]
    # Newest first: what was just noted is usually what is next.
    return [row(_clip(task["text"]), " · ".join(x for x in (task["stamp"], where) if x),
                "Tasks", "checkbox-symbolic", "Done", ("task-done", str(path), task["line"]),
                300 - rank)
            for rank, task in enumerate(reversed(hits[-12:]))]


def complete_task(path, line):
    """Tick the task on that line of the inbox. True if the file changed."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    updated = extras.set_task_done(text, line)
    if updated == text:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


# --------------------------------------------------------------- git, time

def git_rows(projects, status_of=extras.git_status):
    rows = []
    for rank, item in enumerate(extras.git_overview(projects, status_of)[:20]):
        rows.append(row(
            item["name"], f"{item['text']}  ·  {item['path'].replace(str(Path.home()), '~')}",
            "Git", "emblem-important-symbolic" if item["attention"] else "emblem-ok-symbolic",
            "Terminal",
            ("run", ["gnome-terminal", f"--working-directory={item['path']}"], item["path"]),
            300 - rank))
    return rows or [row("No projects registered", "Add one in Projects", "Git",
                        "folder-symbolic", score=300)]


def time_rows(report):
    """report: the service's GetTimeReport rows, or None if it did not answer."""
    if report is None:
        return [row("Project time is unavailable", "The project service is not answering",
                    "Time", "preferences-system-time-symbolic", score=300)]
    if not report:
        return [row("No project time recorded yet",
                    "Time counts while a project is active and you are at the machine",
                    "Time", "preferences-system-time-symbolic", score=300)]
    return [row(item["name"],
                f"{extras.format_duration(item['today'])} today  ·  "
                f"{extras.format_duration(item['week'])} in the last 7 days",
                "Time", "preferences-system-time-symbolic", score=300 - rank)
            for rank, item in enumerate(report[:15])]


# ----------------------------------------------------------- content search

CONTENT_LIMIT = 12
CONTENT_MIN_CHARS = 3


def parse_rg(output, root):
    """ripgrep `-0 --line-number --no-heading` output -> [(path, line, text)].

    Each record is "path NUL line:text". The NUL is what makes this safe for
    file names that contain a colon.
    """
    hits = []
    for record in (output or "").split("\n"):
        path, nul, rest = record.partition("\0")
        number, colon, text = rest.partition(":")
        if nul and colon and number.isdigit():
            full = path if os.path.isabs(path) else os.path.join(str(root), path)
            hits.append((full, int(number), text.strip()))
    return hits


def content_search(root, text, timeout=3):
    """Lines in files under root that contain text, as parse_rg() returns."""
    if len(text) < CONTENT_MIN_CHARS or not root or not shutil.which("rg"):
        return []
    try:
        out = subprocess.run(
            ["rg", "-0", "--line-number", "--no-heading", "--color", "never", "--smart-case",
             "--fixed-strings", "--max-count", "3", "--max-columns", "300",
             "--max-filesize", "1M", "--", text, "."],
            cwd=str(root), capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_rg(out.stdout, root)[:200]


def content_rows(hits, root):
    rows = []
    seen = {}
    for path, line, text in hits:
        # At most two lines from one file, so one noisy file cannot fill the list.
        seen[path] = seen.get(path, 0) + 1
        if seen[path] > 2:
            continue
        relative = os.path.relpath(path, str(root)) if root else path
        rows.append(row(_clip(text, 120), f"{relative}:{line}", "In Files",
                        "text-x-generic-symbolic", "Line", ("open", path, line),
                        300 - len(rows)))
        if len(rows) >= CONTENT_LIMIT:
            break
    return rows


def editor_argv(path, line):
    """Open path at line in an editor that can take a line, else just open it."""
    if line and shutil.which("code"):
        return ["code", "--goto", f"{path}:{line}"]
    return None


# ---------------------------------------------------------------- processes

# Ending one of these ends the session or the thing you are typing into.
PROTECTED_PROCESSES = {
    "systemd", "gnome-shell", "gnome-session-b", "gnome-session-binary", "Xorg", "Xwayland",
    "dbus-daemon", "dbus-broker", "gdm-x-session", "gdm-wayland-ses", "pipewire",
    "pulseaudio", "wireplumber", "gnome-keyring-d", "ibus-daemon",
}


def list_processes(proc="/proc", uid=None):
    """[{pid, name, cmdline, start}] for this user's processes."""
    uid = os.getuid() if uid is None else uid
    found = []
    for entry in os.listdir(proc):
        if not entry.isdigit():
            continue
        base = os.path.join(proc, entry)
        try:
            if os.stat(base).st_uid != uid:
                continue
            with open(os.path.join(base, "stat"), encoding="utf-8", errors="replace") as handle:
                stat_line = handle.read()
            with open(os.path.join(base, "cmdline"), "rb") as handle:
                cmdline = handle.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
        except OSError:
            continue
        # comm is in brackets and may itself contain spaces or brackets.
        name = stat_line[stat_line.find("(") + 1:stat_line.rfind(")")]
        fields = stat_line[stat_line.rfind(")") + 2:].split()
        if not cmdline or len(fields) < 20:
            continue  # kernel thread, or gone
        found.append({"pid": int(entry), "name": name, "cmdline": cmdline, "start": fields[19]})
    return found


def process_rows(rest, processes, own_pid=None):
    if len(rest) < 2:
        return [row("End a process", "Type part of its name: kill <name>", "Processes",
                    "process-stop-symbolic", score=300)]
    folded = rest.casefold()
    own_pid = os.getpid() if own_pid is None else own_pid
    hits = [p for p in processes
            if p["pid"] != own_pid and p["name"] not in PROTECTED_PROCESSES
            and (folded in p["name"].casefold() or folded in p["cmdline"].casefold())]
    hits.sort(key=lambda p: (not p["name"].casefold().startswith(folded), p["name"].casefold(), p["pid"]))
    if not hits:
        return [row("No process of yours matches", "Session processes are never offered",
                    "Processes", "process-stop-symbolic", score=300)]
    return [row(f"End {p['name']}", f"pid {p['pid']}  ·  {_clip(p['cmdline'], 90)}",
                "Processes", "process-stop-symbolic", "End",
                ("signal", p["pid"], p["start"]), 300 - rank)
            for rank, p in enumerate(hits[:10])]


def end_process(pid, start, proc="/proc"):
    """Ask pid to quit, if it is still the process that was listed.

    A pid can be reused between listing and Enter; the start time cannot, so
    it is checked first. SIGTERM only: the process gets to save and clean up.
    """
    for process in list_processes(proc):
        if process["pid"] == pid:
            if process["start"] != start or process["name"] in PROTECTED_PROCESSES:
                return False
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                return False
            return True
    return False


# ---------------------------------------------------------------------- ssh

_SSH_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def parse_ssh_hosts(text):
    """Host aliases from ssh_config text: no patterns, nothing ssh would read
    as an option."""
    hosts = []
    for line in (text or "").splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[0].lower() == "host":
            for name in parts[1:]:
                if _SSH_HOST.match(name) and name not in hosts:
                    hosts.append(name)
    return hosts


def ssh_rows(rest, hosts):
    folded = rest.casefold()
    hits = [h for h in hosts if folded in h.casefold()]
    hits.sort(key=lambda h: (not h.casefold().startswith(folded), h.casefold()))
    if not hits:
        return [row("No SSH host matches" if hosts else "No hosts in ~/.ssh/config",
                    "Hosts come from the Host lines of ~/.ssh/config", "SSH",
                    "network-server-symbolic", score=300)]
    return [row(f"ssh {host}", "Opens in a terminal", "SSH", "network-server-symbolic", "Connect",
                ("run", ["gnome-terminal", "--", "ssh", host], None), 300 - rank)
            for rank, host in enumerate(hits[:12])]


# ----------------------------------------------------------------- branches

def list_branches(path, timeout=3):
    """(branches, current) of the repository at path; ([], "") if none."""
    try:
        out = subprocess.run(
            ["git", "--no-optional-locks", "-C", str(path), "branch",
             "--format=%(HEAD)%(refname:short)"],
            capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return [], ""
    if out.returncode != 0:
        return [], ""
    branches, current = [], ""
    for line in out.stdout.splitlines():
        if not line[1:] or line[1:].startswith("("):
            continue  # detached HEAD is listed as "(HEAD detached at ...)"
        branches.append(line[1:])
        if line[0] == "*":
            current = line[1:]
    return branches, current


def branch_rows(rest, path, branches, current):
    if not path:
        return [row("No active project", "Switching branches works on the active project",
                    "Branches", "media-playlist-shuffle-symbolic", score=300)]
    if not branches:
        return [row("The active project is not a git repository", path, "Branches",
                    "media-playlist-shuffle-symbolic", score=300)]
    folded = rest.casefold()
    hits = [b for b in branches if folded in b.casefold() and b != current]
    hits.sort(key=lambda b: (not b.casefold().startswith(folded), b.casefold()))
    if not hits:
        return [row(f"On {current}" if current else "No other branch",
                    "No other branch matches", "Branches",
                    "media-playlist-shuffle-symbolic", score=300)]
    return [row(f"Switch to {branch}", f"from {current or 'detached HEAD'}  ·  git refuses if it would lose work",
                "Branches", "media-playlist-shuffle-symbolic", "Switch",
                ("run-notify", f"Switch to {branch}",
                 ["git", "-C", path, "switch", "--", branch], path), 300 - rank)
            for rank, branch in enumerate(hits[:12])]


# -------------------------------------------------------------------- timer

_TIMER = re.compile(r"^(\d+(?:\.\d+)?)\s*(s|sec|secs|seconds?|m|min|mins|minutes?|h|hr|hrs|hours?)?(?:\s+(.*))?$",
                    re.I | re.S)
TIMER_MAX_S = 24 * 3600


def parse_timer(rest):
    """(seconds, label) for "10m tea", "90s", "1.5h standup"; None otherwise.

    A bare number is minutes, which is what a desk timer nearly always is.
    """
    match = _TIMER.match((rest or "").strip())
    if not match:
        return None
    amount = float(match.group(1))
    unit = (match.group(2) or "m").lower()[0]
    seconds = int(round(amount * {"s": 1, "m": 60, "h": 3600}[unit]))
    if not 1 <= seconds <= TIMER_MAX_S:
        return None
    return seconds, _fold(match.group(3) or "")


def timer_rows(rest):
    parsed = parse_timer(rest)
    if not parsed:
        return [row("Start a timer", "timer 10m tea  ·  timer 90s  ·  timer 1.5h review",
                    "Timer", "alarm-symbolic", score=300)]
    seconds, label = parsed
    length = extras.format_duration(seconds) if seconds >= 60 else f"{seconds} s"
    return [row(f"Start a {length} timer" + (f": {label}" if label else ""),
                "A notification when it is up", "Timer", "alarm-symbolic", "Start",
                ("timer", seconds, label), 300)]


def timer_argv(seconds, label, now=None):
    """A transient systemd user timer, so it outlives the palette."""
    unit = f"adaptive-timer-{int(now if now is not None else time.time())}"
    return ["systemd-run", "--user", "--quiet", f"--unit={unit}", f"--on-active={int(seconds)}",
            "--timer-property=AccuracySec=1s", "--",
            "notify-send", "--urgency=critical", "--app-name=Adaptive Timer",
            "--icon=alarm-symbolic", "Time is up", label or "Your timer has finished"]


# ---------------------------------------------------------------- shortcuts

def format_accelerator(accel):
    """"<Super><Alt>n" -> "Super+Alt+N"."""
    parts = re.findall(r"<([^>]+)>", accel or "")
    key = re.sub(r"<[^>]+>", "", accel or "")
    names = {"primary": "Ctrl", "control": "Ctrl", "mod1": "Alt", "mod4": "Super"}
    shown = [names.get(p.lower(), p.capitalize()) for p in parts]
    if key:
        shown.append(key.upper() if len(key) == 1 else key.replace("_", " ").title())
    return "+".join(shown)


def shortcut_rows(rest, shortcuts):
    """shortcuts: [(title, accelerator)], however the caller gathered them."""
    folded = rest.casefold()
    rows = []
    for title, accel in shortcuts:
        shown = format_accelerator(accel)
        if not shown or (folded not in title.casefold() and folded not in shown.casefold()):
            continue
        rows.append(row(title, shown, "Shortcuts", "input-keyboard-symbolic", shown,
                        score=300 - len(rows)))
    return rows[:24] or [row("No shortcut matches", "keys <text>", "Shortcuts",
                             "input-keyboard-symbolic", score=300)]


# ------------------------------------------------------------ new project

def new_project_rows(rest, templates):
    words = rest.split(None, 1)
    if not words:
        return [row(f"new {name} <folder>", template.get("description", ""), "New Project",
                    "folder-new-symbolic", score=300 - rank)
                for rank, (name, template) in enumerate(sorted(templates.items()))] or [
            row("No project templates", "Add one to ~/.config/adaptive-desktop/project-templates",
                "New Project", "folder-new-symbolic", score=300)]
    name = words[0]
    if name not in templates:
        return [row(f"No template “{name}”", "Templates: " + ", ".join(sorted(templates)),
                    "New Project", "folder-new-symbolic", score=300)]
    if len(words) < 2:
        return [row(f"new {name} <folder>", "Type where the project goes, e.g. ~/code/thing",
                    "New Project", "folder-new-symbolic", score=300)]
    folder = os.path.abspath(os.path.expanduser(words[1].strip()))
    exists = "adds to the existing folder" if os.path.isdir(folder) else "creates the folder"
    return [row(f"Create {os.path.basename(folder)} from {name}",
                f"{folder.replace(str(Path.home()), '~')}  ·  {exists}", "New Project",
                "folder-new-symbolic", "Create",
                ("run-notify", f"New project {os.path.basename(folder)}",
                 [str(REPO / "scripts" / "project-cli.py"), "new", folder,
                  "--template", name, "--active"], None), 300)]


# ------------------------------------------------------------ your commands

_HEADER = re.compile(r"^#\s*(title|description)\s*:\s*(.+)$", re.I)


def user_commands(directory=None, uid=None):
    """[{title, description, path}] for the executables in the commands folder.

    Only regular files you own that nobody else can write are offered: the
    palette runs them as you, so they have to be yours. A "# title:" and
    "# description:" line near the top name the command; otherwise the file
    name does.
    """
    directory = Path(directory or COMMANDS_DIR)
    uid = os.getuid() if uid is None else uid
    commands = []
    try:
        entries = sorted(directory.iterdir())
    except OSError:
        return commands
    for path in entries:
        try:
            info = path.lstat()
        except OSError:
            continue
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != uid
                or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
                or not info.st_mode & stat.S_IXUSR or path.name.startswith(".")):
            continue
        title = re.sub(r"[-_]+", " ", path.stem).strip().capitalize() or path.name
        description = "Your command"
        try:
            with path.open(encoding="utf-8", errors="replace") as handle:
                for _ in range(12):
                    match = _HEADER.match(handle.readline().strip())
                    if match and match.group(1).lower() == "title":
                        title = match.group(2).strip()
                    elif match:
                        description = match.group(2).strip()
        except OSError:
            pass
        commands.append({"title": title, "description": description, "path": str(path)})
    return commands[:60]
