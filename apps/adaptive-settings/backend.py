"""Adaptive Settings - everything the window reads and writes, without GTK.

Kept apart from main.py so it can be exercised from a plain Python process
(scripts/verify-adaptive-settings.py) where no display or GTK is available.

Nothing here owns state of its own. Projects belong to the Project Context
Service, workspaces and shortcuts to gsettings, session facts to
scripts/session-cli.py and live verification to
scripts/record-live-verification.py; this module only reads them and asks them
to change, so Settings can never disagree with the CLIs.
"""

import ast
import importlib.util
import json
import os
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
CONFIG_DIR = Path.home() / ".config" / "adaptive-desktop"
CLAMSHELL_FLAG = CONFIG_DIR / "clamshell"

MEDIA_KEYS = "org.gnome.settings-daemon.plugins.media-keys"
CUSTOM_KEYBINDING = MEDIA_KEYS + ".custom-keybinding"
KEYBINDING_BASE = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"

# Schemas whose accelerators win the grab over a media-keys custom shortcut.
# A shortcut that duplicates one of these never binds, and the only symptom is
# "Failed to grab accelerator" at login (docs/BACKLOG.md, live-only traps).
GRABBING_SCHEMAS = (
    "org.gnome.desktop.wm.keybindings",
    "org.gnome.shell.keybindings",
    "org.gnome.mutter.keybindings",
    "org.gnome.mutter.wayland.keybindings",
)

SEARCH_PROVIDERS = "org.gnome.desktop.search-providers"
PROJECT_PROVIDER_ID = "adaptive-project-context.desktop"

PLOCATE_DBS = (Path("/var/lib/plocate/plocate.db"), Path("/var/lib/mlocate/mlocate.db"))
APT_CHECK = Path("/usr/lib/update-notifier/apt-check")

FOCUS_CHOICES = ("", "on", "off")


def _load_script(name):
    """Import one of scripts/*.py by file name; they have hyphens in them."""
    path = REPO / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace("-", "_")[:-3], path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(argv, timeout=10):
    """Run a command and return (ok, stdout, stderr). Never raises."""
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return out.returncode == 0, out.stdout, out.stderr
    except (OSError, subprocess.SubprocessError) as error:
        return False, "", str(error)


# ------------------------------------------------------------------ gsettings

def parse_strv(text):
    """A gsettings array as printed, e.g. "@as []" or "['a', 'b']"."""
    text = (text or "").strip()
    if text.startswith("@as "):
        text = text[4:]
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value] if isinstance(value, (list, tuple)) else []


def format_strv(values):
    return "[" + ", ".join(repr(str(v)) for v in values) + "]"


def parse_string(text):
    text = (text or "").strip()
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return text
    return value if isinstance(value, str) else text


def gsettings_get(schema, key):
    ok, out, _ = run(["gsettings", "get", schema, key])
    return out.strip() if ok else None


def gsettings_set(schema, key, value):
    ok, _, err = run(["gsettings", "set", schema, key, value])
    return ok, err.strip()


# ---------------------------------------------------------------- shortcuts

_MODIFIER = re.compile(r"<([^>]+)>")
_MODIFIER_ALIASES = {
    "control": "ctrl", "primary": "ctrl", "ctl": "ctrl",
    "mod1": "alt", "mod4": "super", "meta": "super",
}


def normalize_accel(accel):
    """A comparable form of a GTK accelerator: sorted modifiers + key.

    "<Alt>space", "<alt>Space" and "<Mod1>space" all normalize alike, so a
    conflict is found however either side spelled it. Empty and disabled
    accelerators normalize to "".
    """
    accel = (accel or "").strip()
    if not accel or accel.lower() == "disabled":
        return ""
    modifiers = sorted({
        _MODIFIER_ALIASES.get(m.lower(), m.lower()) for m in _MODIFIER.findall(accel)
    })
    key = _MODIFIER.sub("", accel).strip().lower()
    return "".join(f"<{m}>" for m in modifiers) + key


def parse_list_recursively(text):
    """`gsettings list-recursively` output -> [(schema, key, raw_value)]."""
    rows = []
    for line in (text or "").splitlines():
        parts = line.split(" ", 2)
        if len(parts) == 3:
            rows.append((parts[0], parts[1], parts[2]))
    return rows


def find_conflicts(accel, grabbed):
    """Which grabbing keybindings already use accel.

    grabbed is [(schema, key, raw_value)] as parse_list_recursively returns.
    """
    wanted = normalize_accel(accel)
    if not wanted:
        return []
    hits = []
    for schema, key, raw in grabbed:
        values = parse_strv(raw) if raw.strip().startswith(("[", "@as")) else [parse_string(raw)]
        if any(normalize_accel(v) == wanted for v in values):
            hits.append(f"{schema} {key}")
    return hits


def grabbing_bindings():
    rows = []
    for schema in GRABBING_SCHEMAS:
        ok, out, _ = run(["gsettings", "list-recursively", schema])
        if ok:
            rows.extend(parse_list_recursively(out))
    return rows


def adaptive_shortcuts():
    """The custom shortcuts scripts/install-keybindings.sh owns."""
    paths = parse_strv(gsettings_get(MEDIA_KEYS, "custom-keybindings"))
    shortcuts = []
    for path in paths:
        slot = path.rstrip("/").rsplit("/", 1)[-1]
        if not slot.startswith("adaptive-"):
            continue
        schema = f"{CUSTOM_KEYBINDING}:{path}"
        shortcuts.append({
            "path": path,
            "slot": slot,
            "name": parse_string(gsettings_get(schema, "name") or slot),
            "command": parse_string(gsettings_get(schema, "command") or ""),
            "binding": parse_string(gsettings_get(schema, "binding") or ""),
        })
    return shortcuts


def set_shortcut(path, accel):
    return gsettings_set(f"{CUSTOM_KEYBINDING}:{path}", "binding", repr(accel or ""))


# ------------------------------------------------------------- search index

def plocate_db():
    for path in PLOCATE_DBS:
        if path.exists():
            return path
    return None


def describe_age(seconds):
    if seconds is None:
        return "never built"
    seconds = max(0, int(seconds))
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds >= size:
            count = seconds // size
            return f"{count} {unit}{'s' if count != 1 else ''} old"
    return "just refreshed"


def project_provider_enabled():
    disabled = parse_strv(gsettings_get(SEARCH_PROVIDERS, "disabled"))
    return PROJECT_PROVIDER_ID not in disabled


def set_project_provider(enabled):
    disabled = [d for d in parse_strv(gsettings_get(SEARCH_PROVIDERS, "disabled"))
                if d != PROJECT_PROVIDER_ID]
    if not enabled:
        disabled.append(PROJECT_PROVIDER_ID)
    return gsettings_set(SEARCH_PROVIDERS, "disabled", format_strv(disabled))


# ----------------------------------------------------------------- updates

def parse_apt_check(text):
    """apt-check prints "upgrades;security" on stderr. None if unreadable."""
    match = re.search(r"(\d+);(\d+)", text or "")
    return (int(match.group(1)), int(match.group(2))) if match else None


def ubuntu_updates():
    if not APT_CHECK.exists():
        return None
    _, out, err = run([str(APT_CHECK)], timeout=60)
    return parse_apt_check(err or out)


def git(*args, timeout=10):
    ok, out, _ = run(["git", "-C", str(REPO), *args], timeout=timeout)
    return out.strip() if ok else ""


def repo_state():
    """Where this checkout of Adaptive Desktop stands. Read-only, no network."""
    if not (REPO / ".git").exists():
        return None
    status = git("status", "--porcelain")
    return {
        "branch": git("rev-parse", "--abbrev-ref", "HEAD") or "?",
        "head": git("rev-parse", "--short", "HEAD"),
        "subject": git("log", "-1", "--format=%s"),
        "date": git("log", "-1", "--format=%cr"),
        "dirty": len([line for line in status.splitlines() if line.strip()]),
        "tag": git("describe", "--tags", "--abbrev=0"),
        "upstream": git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"),
    }


def parse_ahead_behind(text):
    """`git rev-list --left-right --count HEAD...@{u}` -> (ahead, behind)."""
    parts = (text or "").split()
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return None
    return int(parts[0]), int(parts[1])


def update_blocker(state, ahead_behind):
    """Why a fast-forward update must not run, or "" when it may.

    Recovery before risk: an update only ever fast-forwards a clean checkout,
    so there is never a merge to resolve in the middle of a desktop session.
    """
    if state is None:
        return "Not a git checkout"
    if not state.get("upstream"):
        return "This branch tracks no remote branch"
    if state.get("dirty"):
        return f"{state['dirty']} uncommitted change(s) - commit or stash them first"
    if ahead_behind is None:
        return "Check for updates first"
    ahead, behind = ahead_behind
    if behind == 0:
        return "Already up to date"
    if ahead:
        return f"Local branch has {ahead} unpushed commit(s); update it by hand"
    return ""


# ----------------------------------------------------------------- session

def session_facts():
    return _load_script("session-cli.py").facts()


def recovery_steps():
    return list(_load_script("session-cli.py").RECOVERY_STEPS)


def clamshell_enabled():
    return CLAMSHELL_FLAG.exists()


def set_clamshell(enabled):
    """The opt-in adaptive-lid-watch.sh reads. Battery suspend is untouched."""
    if enabled:
        CLAMSHELL_FLAG.parent.mkdir(parents=True, exist_ok=True)
        CLAMSHELL_FLAG.touch()
    else:
        try:
            CLAMSHELL_FLAG.unlink()
        except FileNotFoundError:
            pass


# ----------------------------------------------------------- watchdog

WATCHDOG_STATE = Path.home() / ".cache" / "adaptive-desktop" / "shell-watchdog.json"


def watchdog_tripped():
    """Whether the shell's crash watchdog has stood the desktop down."""
    try:
        return bool(json.loads(WATCHDOG_STATE.read_text(encoding="utf-8")).get("tripped"))
    except (OSError, ValueError, AttributeError):
        return False


def rearm_watchdog():
    """Clear the record; the shell builds the desktop on its next start."""
    WATCHDOG_STATE.parent.mkdir(parents=True, exist_ok=True)
    WATCHDOG_STATE.write_text('{"starts": [], "tripped": false}\n', encoding="utf-8")


def workspace_name_rows(names, count):
    """(index, name) for each workspace, padded to how many there are."""
    names = list(names)
    return [(i, names[i] if i < len(names) else "") for i in range(max(count, len(names)))]


def set_workspace_name(names, index, name):
    """The workspace-names list with one slot changed, trailing blanks dropped."""
    names = list(names)
    while len(names) <= index:
        names.append("")
    names[index] = name.strip()
    while names and not names[-1]:
        names.pop()
    return names


# ------------------------------------------------------- live verification

def verification():
    """[(check, entry)] in the recorder's order; entry is {} when pending."""
    recorder = _load_script("record-live-verification.py")
    try:
        checks = recorder.latest_report().get("checks", {})
    except (OSError, ValueError):
        checks = {}
    return [(check, checks.get(check["id"], {})) for check in recorder.CHECKS]


def record_verification(check_id, result, note=""):
    return _load_script("record-live-verification.py").record_result(check_id, result, note)


# ---------------------------------------------------------------- projects

def workspace_choice(index, count):
    """Dropdown position for a project's workspace_index (0 means none)."""
    try:
        index = int(index)
    except (TypeError, ValueError):
        return 0
    return index + 1 if 0 <= index < count else 0


def focus_choice(project):
    value = project.get("metadata", {}).get("focus", "")
    return FOCUS_CHOICES.index(value) if value in FOCUS_CHOICES else 0


def sorted_projects(projects, active_id):
    """Active first, then most recently used, then by name."""
    return sorted(
        projects.values(),
        key=lambda p: (p.get("id") != active_id,
                       -int(p.get("last_active_at", 0) or 0),
                       str(p.get("name", "")).casefold()),
    )


def home_relative(path):
    home = str(Path.home())
    return "~" + path[len(home):] if path == home or path.startswith(home + os.sep) else path


def projects_from_file():
    """Read-only fallback for when the service is not running."""
    try:
        data = json.loads((CONFIG_DIR / "projects.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, ""
    return data.get("projects", {}), data.get("active_id") or ""
