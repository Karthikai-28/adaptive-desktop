#!/usr/bin/env python3
"""Register every git repository under home as an Adaptive project.

Projects were added by hand, so the registry held two entries while the machine
had dozens of repositories on it. This finds them and keeps the registry in
step, recording the git state each one is in so the project view can sort and
describe them without shelling out per card.

    ./scripts/project-scan.py            # scan and register
    ./scripts/project-scan.py --dry-run  # show what would change
    ./scripts/project-scan.py --prune    # also drop projects whose path is gone

Ordering is by last commit, most recent first: the repository you touched this
morning is the one you want at the top.
"""

import argparse
import json
import subprocess
import time
import uuid
from pathlib import Path

REGISTRY = Path.home() / ".config/adaptive-desktop/projects.json"

# Directories that never contain a repository worth listing, or that hold
# thousands of vendored ones.
SKIP = {
    "node_modules", "__pycache__", "venv", ".venv", "site-packages",
    "vendor", "build", "dist", "target", ".cache", ".local", ".config",
    "snap", ".steam", ".nvm", ".cargo", ".rustup", ".gradle", ".m2",
    "Trash", ".trash", ".git",
}

MAX_DEPTH = 4


def git(repo, *args, timeout=5):
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, timeout=timeout,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def find_repos(root):
    """Breadth-first, depth-capped. A repository is not searched for nested
    repositories: submodules and vendored checkouts are not separate projects.

    The scan root is the exception. Home here is itself a git repository - a
    dotfiles checkout - and treating it like any other repo stopped the walk
    dead at the first directory, finding exactly one project on a machine with
    dozens."""
    found = []
    queue = [(root, 0)]

    while queue:
        directory, depth = queue.pop(0)

        try:
            entries = list(directory.iterdir())
        except (PermissionError, OSError):
            continue

        is_repo = any(e.name == ".git" for e in entries)

        if is_repo:
            found.append(directory)

            if directory != root:
                continue

        if depth >= MAX_DEPTH:
            continue

        for entry in entries:
            if entry.is_dir() and not entry.is_symlink():
                if entry.name in SKIP or entry.name.startswith("."):
                    continue
                queue.append((entry, depth + 1))

    return found


def describe(repo):
    """Everything the project view needs, gathered once."""
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD") or "-"
    stamp = git(repo, "log", "-1", "--format=%ct")
    subject = git(repo, "log", "-1", "--format=%s")
    author = git(repo, "log", "-1", "--format=%an")
    remote = git(repo, "config", "--get", "remote.origin.url")
    status = git(repo, "status", "--porcelain")
    commits = git(repo, "rev-list", "--count", "HEAD")

    dirty = len([line for line in status.splitlines() if line.strip()])

    return {
        "branch": branch,
        "last_commit_at": int(stamp) if stamp.isdigit() else 0,
        "last_commit_subject": subject[:120],
        "last_commit_author": author,
        "remote": remote,
        "dirty": dirty,
        "commits": int(commits) if commits.isdigit() else 0,
        "scanned_at": int(time.time()),
    }


def load():
    if REGISTRY.exists():
        try:
            return json.loads(REGISTRY.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"active_id": "", "projects": {}}


def save(data):
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path.home()))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--prune", action="store_true")
    args = ap.parse_args()

    repos = find_repos(Path(args.root))
    data = load()
    projects = data.setdefault("projects", {})
    by_path = {p.get("path"): pid for pid, p in projects.items()}

    added = updated = 0

    for repo in repos:
        path = str(repo)
        info = describe(repo)
        pid = by_path.get(path)

        if pid is None:
            pid = uuid.uuid4().hex[:8]
            now = int(time.time())
            projects[pid] = {
                "id": pid,
                "name": repo.name.replace("-", " ").replace("_", " ").title(),
                "path": path,
                "accent": "",
                "actions": [],
                "pinned_dirs": [],
                "workspace_index": -1,
                "created_at": now,
                "updated_at": now,
                "last_active_at": info["last_commit_at"] or now,
                "metadata": {},
            }
            added += 1
        else:
            updated += 1

        entry = projects[pid]
        entry.setdefault("metadata", {})
        entry["metadata"]["git"] = info
        entry["updated_at"] = int(time.time())

    removed = 0
    if args.prune:
        for pid in [p for p, e in projects.items()
                    if not Path(e.get("path", "")).is_dir()]:
            del projects[pid]
            removed += 1

    print(f"repositories found: {len(repos)}")
    print(f"  added   {added}")
    print(f"  updated {updated}")
    if args.prune:
        print(f"  pruned  {removed}")

    if args.dry_run:
        print("(dry run, registry untouched)")
        return

    save(data)
    print(f"registry: {REGISTRY}")


if __name__ == "__main__":
    main()
