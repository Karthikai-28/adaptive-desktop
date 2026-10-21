"""Reproducible work capsules: small, inspectable manifests for missions and experiments."""
import asyncio
import hashlib
import json
import os
import platform
import re
import subprocess
import time
import uuid
from pathlib import Path

from . import records
from .repos import git_env

ID_RE = re.compile(r"\d{8}-\d{6}-[a-f0-9]{8}")
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
        records.folder("capsules")

    @property
    def root(self):
        return records.folder("capsules")

    async def create(self, mission_id=None, project="", repo="", command="", launch_args=None,
                     parameters=None, datasets=None, results=None, notes=""):
        """Record a capsule. The database is read here, on the event loop; git and the disk work in a thread."""
        mission = self.office.store.mission(int(mission_id)) if mission_id else None
        if mission_id and not mission:
            raise ValueError("no such mission")
        if parameters is not None and not isinstance(parameters, dict):
            raise ValueError("parameters must be a JSON object")
        if len(json.dumps(parameters or {})) > 100_000:
            raise ValueError("parameters are too large (100 KB maximum)")
        project = (project or (mission or {}).get("project") or "").strip()[:80]
        ref = (repo or (mission or {}).get("repo") or "").strip()
        return await asyncio.to_thread(self._write, mission, project, ref, command, launch_args, parameters,
                                       datasets, results, notes)

    def _write(self, mission, project, ref, command, launch_args, parameters, datasets, results, notes):
        resolved = self.office.repos.resolve(ref) if ref else ""
        root = Path(resolved) if resolved else None
        now = time.time()
        cid = time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + "-" + uuid.uuid4().hex[:8]
        git = {}
        if root:
            dirty = _run(root, "status", "--porcelain=v1", "--untracked-files=all").splitlines()
            git = {"root": str(root), "revision": _run(root, "rev-parse", "HEAD"),
                   "branch": _run(root, "branch", "--show-current"), "dirty": dirty[:500],
                   "dirty_truncated": len(dirty) > 500, "locks": _locks(root)}
        data = {
            "schema": 1, "id": cid, "created_at": now, "mission_id": mission["id"] if mission else None,
            "mission": (mission or {}).get("title", ""), "project": project, "git": git,
            "runtime": {"system": platform.system(), "release": platform.release(),
                        "machine": platform.machine(), "python": platform.python_version()},
            "command": str(command or "").strip()[:10_000], "launch_args": _clean_list(launch_args),
            "parameters": parameters or {}, "datasets": _clean_list(datasets), "results": _clean_list(results),
            "notes": str(notes or "").strip()[:20_000],
        }
        path = self.root / f"{cid}.json"
        records.write_json(path, data)
        return {**data, "path": str(path)}

    def list(self, limit=100, mission_id=None):
        """Newest first. With mission_id, every capsule of that mission (the limit applies after filtering)."""
        rows = []
        for p in sorted(self.root.glob("*.json"), reverse=True):
            if limit is not None and len(rows) >= limit:
                break
            if not ID_RE.fullmatch(p.stem):
                continue
            try:
                d = json.loads(p.read_text())
            except (OSError, ValueError):
                continue
            if mission_id is not None and d.get("mission_id") != mission_id:
                continue
            rows.append({k: d.get(k) for k in ("id", "created_at", "mission_id", "mission", "project")})
        return rows

    def get(self, cid):
        if not ID_RE.fullmatch(cid or ""):
            return None
        p = self.root / f"{cid}.json"
        try:
            d = json.loads(p.read_text())
        except (OSError, ValueError):
            return None
        return {**d, "path": str(p)} if isinstance(d, dict) else None
