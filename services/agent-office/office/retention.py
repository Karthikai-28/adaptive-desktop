"""Bounded retention for generated, reproducible Office artifacts."""
import time
from pathlib import Path

from .config import COMPANY

KINDS = {"capsules", "exports"}


class Retention:
    def inspect(self, days=90, kinds=None, apply=False):
        days = int(days)
        if days < 1 or days > 3650:
            raise ValueError("retention days must be between 1 and 3650")
        selected = set(kinds or KINDS)
        if not selected or not selected <= KINDS:
            raise ValueError("retention kinds must be capsules and/or exports")
        cutoff = time.time() - days * 86400
        rows = []
        for kind in sorted(selected):
            root = (COMPANY / kind).resolve()
            for p in root.glob("*.json"):
                if p.is_file() and p.stat().st_mtime < cutoff:
                    rows.append({"path": str(p.relative_to(COMPANY)), "bytes": p.stat().st_size,
                                 "modified_at": p.stat().st_mtime})
        if apply:
            for row in rows:
                p = (COMPANY / row["path"]).resolve()
                if p.parent in {(COMPANY / x).resolve() for x in KINDS}:
                    p.unlink(missing_ok=True)
        return {"days": days, "kinds": sorted(selected), "apply": bool(apply), "files": rows,
                "count": len(rows), "bytes": sum(x["bytes"] for x in rows)}
