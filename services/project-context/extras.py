"""Project features that need neither GTK nor D-Bus.

The Project Context Service, scripts/project-cli.py and the Command palette
all use these, and scripts/verify-feature-logic.py checks them in a plain
Python process:

  git           parse_git_status(), git_status(), git_overview() - every
                project's branch and how much is uncommitted or unpushed.
  time          add_time(), summarize_time() - seconds per project per day,
                counted only while you are at the machine.
  startup       normalize_startup(), startup_argv() - commands a project runs
                when it is resumed.
  tasks         parse_tasks(), set_task_done() - the quick-note inbox read as
                a task list.
  templates     load_templates(), apply_template() - folders, files and
                settings a new project starts with.
"""

import datetime
import json
import os
import re
import subprocess
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "adaptive-desktop"

# ---------------------------------------------------------------------- git


def parse_git_status(text):
    """`git status --porcelain=v1 --branch` -> a dict, or None if not a repo.

    The same reading as the shell's adaptiveUtil.parseGitStatus, so the top
    bar and the all-projects view never disagree.
    """
    lines = [line for line in (text or "").split("\n") if line]
    if not lines or not lines[0].startswith("## "):
        return None

    head = lines[0][3:]
    status = {"branch": "", "ahead": 0, "behind": 0, "dirty": 0, "detached": False}
    if head.startswith("No commits yet on "):
        status["branch"] = head[len("No commits yet on "):]
    elif head.startswith("HEAD (no branch)"):
        status["branch"] = "detached"
        status["detached"] = True
    else:
        status["branch"] = head.split("...")[0].split(" ")[0]
        ahead = re.search(r"ahead (\d+)", head)
        behind = re.search(r"behind (\d+)", head)
        status["ahead"] = int(ahead.group(1)) if ahead else 0
        status["behind"] = int(behind.group(1)) if behind else 0
    status["dirty"] = len(lines) - 1
    return status


def format_git_status(status):
    """"main", "main ±3", "main ±3 ↑1 ↓2"; "" for no repository."""
    if not status:
        return ""
    parts = [status["branch"]]
    if status["dirty"]:
        parts.append(f"±{status['dirty']}")
    if status["ahead"]:
        parts.append(f"↑{status['ahead']}")
    if status["behind"]:
        parts.append(f"↓{status['behind']}")
    return " ".join(parts)


def git_status(path, timeout=4):
    """The parsed status of the repository at path, or None."""
    try:
        out = subprocess.run(
            ["git", "--no-optional-locks", "-C", str(path), "status", "--porcelain=v1", "--branch"],
            capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_git_status(out.stdout) if out.returncode == 0 else None


def needs_attention(status):
    return bool(status and (status["dirty"] or status["ahead"] or status["behind"]))


def git_overview(projects, status_of=git_status):
    """[{id, name, path, status, text, attention}] for every project.

    Projects with work to commit, push or pull come first, the most
    uncommitted at the top; clean ones and folders that are not repositories
    follow by name.
    """
    rows = []
    for pid, project in (projects or {}).items():
        status = status_of(project.get("path", ""))
        rows.append({
            "id": pid,
            "name": project.get("name", pid),
            "path": project.get("path", ""),
            "status": status,
            "text": format_git_status(status) if status else "not a git repository",
            "attention": needs_attention(status),
        })
    rows.sort(key=lambda r: (not r["attention"],
                             -(r["status"]["dirty"] if r["status"] else 0),
                             r["name"].casefold()))
    return rows


# --------------------------------------------------------------------- time

TIME_FILE = CONFIG_DIR / "time.json"
# How long the service waits between ticks, and so the unit time is counted in.
TIME_TICK_S = 60
# Idle longer than this and you are not working on the project.
TIME_IDLE_LIMIT_S = 5 * 60
TIME_KEEP_DAYS = 400


def should_count(active_id, idle_ms, locked):
    """Whether this tick counts towards the active project."""
    return bool(active_id) and not locked and idle_ms < TIME_IDLE_LIMIT_S * 1000


def load_time(path=None):
    try:
        data = json.loads((path or TIME_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"days": {}}
    days = data.get("days") if isinstance(data, dict) else None
    return {"days": days if isinstance(days, dict) else {}}


def save_time(data, path=None):
    path = path or TIME_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def add_time(data, day, project_id, seconds):
    """Add seconds to project_id on day ("YYYY-MM-DD"); drops very old days."""
    bucket = data.setdefault("days", {}).setdefault(day, {})
    bucket[project_id] = int(bucket.get(project_id, 0)) + int(seconds)
    if len(data["days"]) > TIME_KEEP_DAYS:
        for old in sorted(data["days"])[:-TIME_KEEP_DAYS]:
            del data["days"][old]
    return data


def summarize_time(data, days, today):
    """{project_id: seconds} over the last `days` days ending on `today`."""
    end = datetime.date.fromisoformat(today)
    wanted = {(end - datetime.timedelta(days=offset)).isoformat() for offset in range(max(1, days))}
    totals = {}
    for day, bucket in data.get("days", {}).items():
        if day in wanted and isinstance(bucket, dict):
            for pid, seconds in bucket.items():
                totals[pid] = totals.get(pid, 0) + int(seconds)
    return totals


def format_duration(seconds):
    """"0 min", "45 min", "2 h 05 min"."""
    minutes = int(seconds) // 60
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d} min"


def time_report(data, projects, today, days=(1, 7)):
    """[{id, name, today, week}] busiest this week first; removed projects
    keep their time under the id they had."""
    spans = [summarize_time(data, span, today) for span in days]
    rows = []
    for pid in set().union(*spans):
        name = (projects or {}).get(pid, {}).get("name") or f"(removed project {pid})"
        rows.append({"id": pid, "name": name,
                     "today": spans[0].get(pid, 0), "week": spans[-1].get(pid, 0)})
    rows.sort(key=lambda r: (-r["week"], r["name"].casefold()))
    return rows


# ------------------------------------------------------------------ startup

STARTUP_LIMIT = 8


def normalize_startup(value):
    """metadata.startup as [{command, terminal}], however it was stored.

    A plain string is one command in a terminal. Anything that is not a
    non-empty command is dropped, and the list is bounded.
    """
    if isinstance(value, str):
        value = [value]
    entries = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, str):
            item = {"command": item}
        if not isinstance(item, dict):
            continue
        command = str(item.get("command", "")).strip()
        if command:
            entries.append({"command": command, "terminal": bool(item.get("terminal", True))})
    return entries[:STARTUP_LIMIT]


def startup_argv(entry, folder):
    """How one startup command is run in the project folder.

    In a terminal it stays open afterwards, so the output - and a failure - is
    there to read. In the background it is a login shell with no window.
    """
    command = entry["command"]
    if entry.get("terminal", True):
        return ["gnome-terminal", f"--working-directory={folder}", "--",
                "bash", "-lc", f"{command}; exec bash"]
    return ["bash", "-lc", command]


# -------------------------------------------------------------------- tasks

_NOTE = re.compile(r"^- (\[[ xX]\] )?(?:(\d{4}-\d{2}-\d{2} \d{2}:\d{2})  )?(.*)$")


def parse_tasks(text):
    """The inbox as tasks: [{line, text, stamp, done}], oldest first.

    Every "- " line the quick note wrote is a task. "- [x] " marks it done;
    a line with no box is open, so notes written before tasks existed count.
    """
    tasks = []
    for number, line in enumerate((text or "").split("\n")):
        match = _NOTE.match(line)
        if match and match.group(3).strip():
            tasks.append({
                "line": number,
                "text": match.group(3).strip(),
                "stamp": match.group(2) or "",
                "done": bool(match.group(1)) and match.group(1)[1] in "xX",
            })
    return tasks


def set_task_done(text, line, done=True):
    """text with the task on that line marked done or open again.

    The line is rewritten only if it still holds a task, so an inbox edited
    in between is never corrupted. Returns the text unchanged otherwise.
    """
    lines = (text or "").split("\n")
    if not 0 <= line < len(lines):
        return text
    match = _NOTE.match(lines[line])
    if not match or not match.group(3).strip():
        return text
    stamp = f"{match.group(2)}  " if match.group(2) else ""
    box = "[x] " if done else ""
    lines[line] = f"- {box}{stamp}{match.group(3)}"
    return "\n".join(lines)


def tasks_path(project_name, notes_dir=None):
    """The inbox the quick note writes to (scripts/adaptive-quick-note.py)."""
    notes_dir = notes_dir or Path.home() / ".local/share/adaptive-desktop/notes"
    return notes_dir / re.sub(r"[^\w.-]", "_", project_name or "General") / "Inbox.md"


# ---------------------------------------------------------------- templates

USER_TEMPLATES = CONFIG_DIR / "project-templates"
_TEMPLATE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _inside(root, relative):
    """root/relative, or None if it would leave root."""
    if not isinstance(relative, str) or not relative.strip() or os.path.isabs(relative):
        return None
    target = (root / relative).resolve()
    return target if target == root or root in target.parents else None


def load_templates(directories):
    """{name: template} from *.json in the directories; later ones win.

    A template is {"description", "folders": [...], "files": {path: text},
    "pinned": [...], "focus": "on"|"off", "startup": [...], "git": bool}.
    """
    templates = {}
    for directory in directories:
        try:
            paths = sorted(Path(directory).glob("*.json"))
        except OSError:
            continue
        for path in paths:
            if not _TEMPLATE_NAME.match(path.stem):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict):
                templates[path.stem] = data
    return templates


def apply_template(template, root):
    """Create the template's folders and files under root.

    Nothing that exists is overwritten, and nothing is created outside root.
    Returns (created, patch): the paths made, and the UpdateProject patch
    (pinned folders, focus, startup commands) for the caller to send.
    """
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    created = []

    for folder in template.get("folders", []):
        target = _inside(root, folder)
        if target and not target.exists():
            target.mkdir(parents=True)
            created.append(str(target))

    files = template.get("files", {})
    for relative, content in (files.items() if isinstance(files, dict) else []):
        target = _inside(root, relative)
        if target and not target.exists() and isinstance(content, str):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content.replace("{name}", root.name), encoding="utf-8")
            created.append(str(target))

    patch = {}
    pinned = [str(t) for t in (_inside(root, p) for p in template.get("pinned", [])) if t]
    if pinned:
        patch["pinned_dirs"] = pinned
    metadata = {}
    if template.get("focus") in ("on", "off"):
        metadata["focus"] = template["focus"]
    startup = normalize_startup(template.get("startup"))
    if startup:
        metadata["startup"] = startup
    if metadata:
        patch["metadata"] = metadata
    return created, patch
