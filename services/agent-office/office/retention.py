"""Bounded retention for Mission Control records.

Audit exports can always be written again from the database. Work capsules cannot (they record a
repository's state at one moment), so a capsule that belongs to a mission is never deleted; only
capsules saved without a mission, and leftover temporary files, age out. Deleting needs the operator key.
"""
import json
import time

from . import records

KINDS = {"capsules", "exports"}


class Retention:
    def inspect(self, days=90, kinds=None, apply=False, mission_ids=frozenset()):
        days = int(days)
        if days < 1 or days > 3650:
            raise ValueError("retention days must be between 1 and 3650")
        selected = set(KINDS if kinds is None else kinds)
        if not selected or not selected <= KINDS:
            raise ValueError("retention kinds must be capsules and/or exports")
        cutoff = time.time() - days * 86400
        rows, paths, kept = [], [], 0
        for kind in sorted(selected):
            root = records.folder(kind)
            for p in sorted(root.iterdir()):
                if not p.is_file() or p.is_symlink() or not (p.suffix == ".json" or p.name.endswith(".tmp")):
                    continue
                st = p.stat()
                if st.st_mtime >= cutoff:
                    continue
                if kind == "capsules" and p.suffix == ".json" and self._mission_of(p) in mission_ids:
                    kept += 1
                    continue
                rows.append({"path": str(p), "bytes": st.st_size, "modified_at": st.st_mtime})
                paths.append(p)
        if apply:
            for p in paths:
                p.unlink(missing_ok=True)
        return {"days": days, "kinds": sorted(selected), "apply": bool(apply), "files": rows,
                "count": len(rows), "bytes": sum(x["bytes"] for x in rows), "kept_mission_capsules": kept}

    @staticmethod
    def _mission_of(p):
        try:
            return json.loads(p.read_text()).get("mission_id")
        except (OSError, ValueError, AttributeError):
            return None
