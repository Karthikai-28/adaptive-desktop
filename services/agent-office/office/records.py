"""Where Mission Control keeps its own records: workflows, work capsules and audit exports.

They live in DATA, which no agent sandbox mounts (agy and local runs get an empty home, Codex and Claude
agents a profile without it), so an agent can neither rewrite a workflow's risk class nor edit evidence
after the fact. Earlier versions kept them in the shared workspace; those files are moved here once.
"""
import json
import os
import shutil
import uuid

from .config import COMPANY, DATA

RECORDS = DATA / "mission-control"
_ready = set()


def folder(kind):
    """The folder for one kind of record ("workflows", "capsules", "exports"), created and migrated."""
    d = RECORDS / kind
    if kind in _ready:
        return d
    d.mkdir(parents=True, exist_ok=True)
    old = COMPANY / kind
    if old.is_dir() and not old.is_symlink():
        for p in old.glob("*.json"):
            if p.is_file() and not p.is_symlink() and not (d / p.name).exists():
                shutil.move(str(p), str(d / p.name))
        try:
            old.rmdir()                     # only when nothing else was left behind
        except OSError:
            pass
    _ready.add(kind)
    return d


def write_json(path, data):
    """Atomically replace path; each writer gets its own temporary file, so concurrent writes never collide."""
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
