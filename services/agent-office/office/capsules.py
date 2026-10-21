"""Reproducible work capsules: small, inspectable manifests for missions and experiments."""
import hashlib
import json
import os
import platform
import re
import subprocess
import time
import uuid
from pathlib import Path

from .config import COMPANY
from .repos import git_env

CAPSULES = COMPANY / "capsules"
LOCK_FILES = ("package-lock.json", "pnpm-lock.yaml", "yarn.lock", "poetry.lock", "uv.lock",
              "Pipfile.lock", "requirements.txt", "Cargo.lock", "go.sum", "CMakePresets.json")


def _run(repo, *args):
    try:
        p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                           timeout=5, env=git_env(os.environ.copy()))
        return p.stdout.strip() if p.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _locks(repo):
    out = []
    for name in LOCK_FILES:
        p = repo / name
        if p.is_file() and p.stat().st_size <= 50 * 1024 * 1024:
            try:
                out.append({"path": name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                            "bytes": p.stat().st_size})
            except OSError:
                pass
    return out


def _clean_list(values, limit=100):
    return [str(v).strip()[:1000] for v in (values or []) if str(v).strip()][:limit]


class Capsules:
    def __init__(self, office):
        self.office = office
        CAPSULES.mkdir(parents=True, exist_ok=True)

    def create(self, mission_id=None, project="", repo="", command="", launch_args=None,
               parameters=None, datasets=None, results=None, notes=""):
        mission = self.office.store.mission(int(mission_id), with_tasks=True) if mission_id else None
        if mission_id and not mission:
            raise ValueError("no such mission")
        project = (project or (mission or {}).get("project") or "").strip()[:80]
        ref = (repo or (mission or {}).get("repo") or "").strip()
        resolved = self.office.repos.resolve(ref) if ref else ""
        root = Path(resolved) if resolved else None
        if parameters is not None and not isinstance(parameters, dict):
            raise ValueError("parameters must be a JSON object")
        raw = json.dumps(parameters or {})
        if len(raw) > 100_000:
            raise ValueError("parameters are too large (100 KB maximum)")
        now = time.time()
        cid = time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + "-" + uuid.uuid4().hex[:8]
        git = {}
        if root:
            dirty = _run(root, "status", "--porcelain=v1", "--untracked-files=all").splitlines()
            git = {"root": str(root), "revision": _run(root, "rev-parse", "HEAD"),
                   "branch": _run(root, "branch", "--show-current"), "dirty": dirty[:500],
                   "dirty_truncated": len(dirty) > 500, "locks": _locks(root)}
        data = {
            "schema": 1, "id": cid, "created_at": now, "mission_id": int(mission_id) if mission_id else None,
            "mission": (mission or {}).get("title", ""), "project": project, "git": git,
            "runtime": {"system": platform.system(), "release": platform.release(),
                        "machine": platform.machine(), "python": platform.python_version()},
            "command": str(command or "").strip()[:10_000], "launch_args": _clean_list(launch_args),
            "parameters": parameters or {}, "datasets": _clean_list(datasets), "results": _clean_list(results),
            "notes": str(notes or "").strip()[:20_000],
        }
        path = CAPSULES / f"{cid}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        os.replace(tmp, path)
        return {**data, "path": str(path.relative_to(COMPANY))}

    def list(self, limit=100):
        rows = []
        for p in sorted(CAPSULES.glob("*.json"), reverse=True)[:limit]:
            try:
                d = json.loads(p.read_text())
                rows.append({k: d.get(k) for k in ("id", "created_at", "mission_id", "mission", "project")})
            except (OSError, ValueError):
                continue
        return rows

    def get(self, cid):
        if not re.fullmatch(r"\d{8}-\d{6}-[a-f0-9]{8}", cid or ""):
            return None
        p = CAPSULES / f"{cid}.json"
        try:
            return {**json.loads(p.read_text()), "path": str(p.relative_to(COMPANY))}
        except (OSError, ValueError):
            return None
