"""Portable audit bundles for a mission, written as ordinary JSON where agents cannot edit them."""
import asyncio
import hashlib
import json
import time

from . import records


class AuditExport:
    def __init__(self, office):
        self.office = office
        records.folder("exports")

    async def mission(self, mid):
        """The database is read here, on the event loop; capsules and the file are handled in a thread."""
        m = self.office.store.mission(int(mid), with_tasks=True)
        if not m:
            raise ValueError("no such mission")
        events = [e for t in m["tasks"] for e in self.office.store.events(task_id=t["id"], limit=5000)]
        return await asyncio.to_thread(self._write, m, events)

    def _write(self, m, events):
        capsules = [c for c in (self.office.capsules.get(row["id"])
                                for row in self.office.capsules.list(limit=None, mission_id=m["id"])) if c]
        policy = {"repository_scope": m.get("repo", ""), "created_by": m.get("created_by", "operator"),
                  "risk": m.get("risk", ""), "workflow_id": m.get("workflow_id", ""),
                  "approved_by": m.get("approved_by", ""), "approved_at": m.get("approved_at"),
                  "allowed_agents": m.get("allowed_agents", [])}
        data = {"schema": 2, "exported_at": time.time(), "mission": m, "events": events, "capsules": capsules,
                "verdicts": m.get("verdicts", []), "policy": policy}
        body = json.dumps(data, sort_keys=True, separators=(",", ":"))
        data["sha256"] = hashlib.sha256(body.encode()).hexdigest()   # over the bundle without this field
        p = records.folder("exports") / f"mission-{m['id']}.json"
        records.write_json(p, data)
        return {"path": str(p), "bytes": p.stat().st_size, "events": len(events), "capsules": len(capsules),
                "sha256": data["sha256"]}
