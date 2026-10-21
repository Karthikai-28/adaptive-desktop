"""Portable audit bundles for a mission, written as ordinary JSON."""
import json
import os
import time

from .config import COMPANY

EXPORTS = COMPANY / "exports"


class AuditExport:
    def __init__(self, office):
        self.office = office
        EXPORTS.mkdir(parents=True, exist_ok=True)

    def mission(self, mid):
        m = self.office.store.mission(int(mid), with_tasks=True)
        if not m:
            raise ValueError("no such mission")
        task_ids = {t["id"] for t in m["tasks"]}
        events = [e for tid in task_ids for e in self.office.store.events(task_id=tid, limit=5000)]
        capsules = []
        for row in self.office.capsules.list(limit=1000):
            if row.get("mission_id") == m["id"]:
                capsules.append(self.office.capsules.get(row["id"]))
        data = {"schema": 1, "exported_at": time.time(), "mission": m, "events": events,
                "capsules": capsules, "policy": {"repository_scope": m.get("repo", ""),
                                                   "created_by": m.get("created_by", "operator")}}
        EXPORTS.mkdir(parents=True, exist_ok=True)
        p, tmp = EXPORTS / f"mission-{m['id']}.json", EXPORTS / f"mission-{m['id']}.tmp"
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        os.replace(tmp, p)
        return {"path": str(p.relative_to(COMPANY)), "bytes": p.stat().st_size,
                "events": len(events), "capsules": len(capsules)}
