"""Git state for Files: per-file badges, a file's last change, a repo summary.

Every git call runs with GIT_OPTIONAL_LOCKS=0 so Files never takes
.git/index.lock while you are committing in a terminal, has a short timeout,
and happens off the main loop (callers use worker threads). A repository
whose status takes too long is left alone for a minute rather than retried
on every directory refresh.
"""

import os
import subprocess
import threading
import time

STATUS_TTL = 2.0
# peek() ignores the TTL; badge refreshes are driven by the info provider.
SLOW_BACKOFF = 60.0

_ENV = dict(os.environ, GIT_OPTIONAL_LOCKS="0", LC_ALL="C")

_root_cache = {}
_root_lock = threading.Lock()

_status_cache = {}
_status_lock = threading.Lock()
_slow = {}

# Badge priority when a folder holds several kinds of change.
RANK = {"conflict": 4, "modified": 3, "added": 2, "untracked": 1}


def _git(root, *args, timeout=3.0):
    return subprocess.run(
        ["git", "-C", root, *args],
        capture_output=True,
        timeout=timeout,
        env=_ENV,
        check=False,
    )


def repo_root(path):
    """Top of the work tree holding path, or None. Cached per directory."""
    directory = path if os.path.isdir(path) else os.path.dirname(path)
    with _root_lock:
        if directory in _root_cache:
            return _root_cache[directory]

    current = directory
    root = None
    while True:
        if _is_git_dir(os.path.join(current, ".git")):
            root = current
            break
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    with _root_lock:
        _root_cache[directory] = root
        if len(_root_cache) > 4096:
            _root_cache.clear()
    return root


def _is_git_dir(dot_git):
    """A real repository, not a stray empty ".git" folder: a directory with
    HEAD in it, or a worktree/submodule ".git" file pointing elsewhere."""
    if os.path.isdir(dot_git):
        return os.path.isfile(os.path.join(dot_git, "HEAD"))
    if os.path.isfile(dot_git):
        try:
            with open(dot_git, "r", encoding="utf-8", errors="replace") as handle:
                return handle.read(8) == "gitdir: "
        except OSError:
            return False
    return False


def _classify(xy):
    x, y = xy[0], xy[1]
    if xy == "??":
        return "untracked"
    if "U" in xy or xy in ("AA", "DD"):
        return "conflict"
    if y in "MD" and y != " ":
        return "modified"
    if x in "AMRCD" and x != " ":
        return "added"
    return None


def status(root):
    """What git reports for root:

    files          {relative path: kind} as git listed them
    untracked_dirs folders git reported whole ("dir/"), untracked inside
    dirs           {"folder/": kind} the strongest change anywhere below
    """
    empty = {"files": {}, "untracked_dirs": set(), "dirs": {}}
    now = time.monotonic()
    with _status_lock:
        cached = _status_cache.get(root)
        if cached and now - cached[0] < STATUS_TTL:
            return cached[1]
        if now - _slow.get(root, -SLOW_BACKOFF) < SLOW_BACKOFF:
            return cached[1] if cached else empty

    try:
        proc = _git(root, "status", "--porcelain=v1", "-z", "--no-renames", "-unormal", timeout=4.0)
    except subprocess.TimeoutExpired:
        with _status_lock:
            _slow[root] = now
        return empty

    result = {"files": {}, "untracked_dirs": set(), "dirs": {}}
    for record in proc.stdout.decode("utf-8", "replace").split("\0"):
        if len(record) < 4:
            continue
        kind = _classify(record[:2])
        if kind is None:
            continue
        rel = record[3:]
        if rel.endswith("/"):
            result["untracked_dirs"].add(rel.rstrip("/"))
            result["dirs"][rel] = kind
        else:
            result["files"][rel] = kind

        # Roll the change up into every containing folder.
        parts = rel.rstrip("/").split("/")[:-1]
        for depth in range(1, len(parts) + 1):
            folder = "/".join(parts[:depth]) + "/"
            if RANK[kind] > RANK.get(result["dirs"].get(folder), 0):
                result["dirs"][folder] = kind

    with _status_lock:
        _status_cache[root] = (time.monotonic(), result)
    return result


def peek(root):
    """(taken_at, table) from the cache without running git, or None."""
    with _status_lock:
        cached = _status_cache.get(root)
    if cached is None:
        return None
    # Monotonic seconds are for the TTL; callers compare against file mtimes.
    age = time.monotonic() - cached[0]
    return time.time() - age, cached[1]


def refresh(root):
    """Run git status now, whatever the cache holds."""
    with _status_lock:
        _status_cache.pop(root, None)
    return status(root)


def badge(path, table=None):
    """"modified" / "added" / "untracked" / "conflict" / None for one path.
    With table given, nothing is run - only that status is consulted."""
    root = repo_root(path)
    if root is None or path == root:
        return None
    rel = os.path.relpath(path, root)
    if rel == ".git" or rel.startswith(".git/"):
        return None
    if table is None:
        table = status(root)

    # Anything inside a folder git reported whole is untracked too.
    parts = rel.split("/")
    for depth in range(len(parts) - 1, 0, -1):
        if "/".join(parts[:depth]) in table["untracked_dirs"]:
            return "untracked"

    if os.path.isdir(path):
        return table["dirs"].get(rel + "/")
    return table["files"].get(rel)


def last_change(path):
    """(author, unix time, subject) of the last commit touching path."""
    root = repo_root(path)
    if root is None:
        return None
    proc = _git(root, "log", "-1", "--format=%an%x1f%at%x1f%s", "--", os.path.relpath(path, root))
    line = proc.stdout.decode("utf-8", "replace").strip()
    if not line:
        return None
    author, when, subject = (line.split("\x1f") + ["", "", ""])[:3]
    try:
        when = int(when)
    except ValueError:
        when = 0
    return author, when, subject


def summary(root):
    """Branch, upstream distance, change counts and the last commit."""
    proc = _git(root, "status", "--porcelain=v2", "--branch", "-z", "-unormal", timeout=4.0)
    info = {"root": root, "branch": None, "ahead": 0, "behind": 0, "upstream": None,
            "staged": 0, "modified": 0, "untracked": 0, "conflicts": 0}

    for record in proc.stdout.decode("utf-8", "replace").split("\0"):
        if record.startswith("# branch.oid "):
            info["oid"] = record[len("# branch.oid "):]
        elif record.startswith("# branch.head "):
            info["branch"] = record[len("# branch.head "):]
        elif record.startswith("# branch.upstream "):
            info["upstream"] = record[len("# branch.upstream "):]
        elif record.startswith("# branch.ab "):
            ahead, behind = record[len("# branch.ab "):].split()
            info["ahead"], info["behind"] = int(ahead), abs(int(behind))
        elif record.startswith(("1 ", "2 ")):
            xy = record[2:4]
            if xy[0] != ".":
                info["staged"] += 1
            if xy[1] != ".":
                info["modified"] += 1
        elif record.startswith("u "):
            info["conflicts"] += 1
        elif record.startswith("? "):
            info["untracked"] += 1

    if info["branch"] == "(detached)":
        oid = info.get("oid") or ""
        info["branch"] = f"detached {oid[:7]}" if oid and oid != "(initial)" else "detached"
    elif info.get("oid") == "(initial)":
        info["branch"] = f"{info['branch']} · no commits"

    log = _git(root, "log", "-1", "--format=%an%x1f%at%x1f%s").stdout.decode("utf-8", "replace").strip()
    if log:
        author, when, subject = (log.split("\x1f") + ["", "", ""])[:3]
        info["last_author"] = author
        info["last_subject"] = subject
        try:
            info["last_at"] = int(when)
        except ValueError:
            info["last_at"] = 0
    return info


def forget(root=None):
    """Drop cached status (after a file operation Files told us about)."""
    with _status_lock:
        if root is None:
            _status_cache.clear()
        else:
            _status_cache.pop(root, None)
