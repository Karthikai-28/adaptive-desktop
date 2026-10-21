"""Small, private evidence search over Office records and explicitly scoped project files."""
import json
import os
import re
from pathlib import Path

from .config import COMPANY
from .repos import SECRET_PRUNE, _is_secret

TEXT_SUFFIXES = {".c", ".cc", ".cpp", ".h", ".hpp", ".py", ".js", ".ts", ".tsx", ".jsx", ".java",
                 ".kt", ".rs", ".go", ".sh", ".zsh", ".md", ".txt", ".json", ".yaml", ".yml", ".toml",
                 ".ini", ".cfg", ".xml", ".launch", ".msg", ".srv", ".action", ".csv", ".log"}


def _terms(q):
    return list(dict.fromkeys(re.findall(r"[\w./:-]{2,}", q.lower())))[:12]


def _hit(terms, text):
    low = text.lower()
    if not all(t in low for t in terms):
        return 0
    return sum(low.count(t) for t in terms)


def _snippet(terms, text, n=280):
    lines = text.splitlines()
    line = next((x.strip() for x in lines if any(t in x.lower() for t in terms)), text.strip())
    return (line[:n] + "…") if len(line) > n else line


class Evidence:
    def __init__(self, office):
        self.office = office

    def search(self, query, mission_id=None, limit=40):
        query = (query or "").strip()
        terms = _terms(query)
        if not terms:
            raise ValueError("search needs at least one word")
        mission = self.office.store.mission(int(mission_id), with_tasks=True) if mission_id else None
        if mission_id and not mission:
            raise ValueError("no such mission")
        out = []

        def add(kind, ref, title, text):
            score = _hit(terms, text)
            if score:
                out.append({"kind": kind, "ref": ref, "title": title,
                            "snippet": _snippet(terms, text), "score": score})

        missions = [mission] if mission else self.office.store.missions(limit=300)
        for m in missions:
            if not m:
                continue
            add("mission", f"mission:{m['id']}", m["title"],
                "\n".join([m["title"], m["objective"], *m["criteria"], m.get("summary", ""), m.get("error", "")]))
        tasks = mission["tasks"] if mission else self.office.store.tasks(limit=1000)
        for t in tasks:
            add("task", f"task:{t['id']}", t["title"],
                "\n".join(str(t.get(k) or "") for k in ("title", "body", "result", "error")))
        for row in self.office.capsules.list(limit=300):
            if mission and row.get("mission_id") != mission["id"]:
                continue
            c = self.office.capsules.get(row["id"])
            add("capsule", c["path"], c.get("mission") or c["id"], json.dumps(c, sort_keys=True))

        roots = []
        project = (mission or {}).get("project") or ""
        if project:
            p = (COMPANY / "projects" / project).resolve()
            if p.is_dir() and COMPANY in p.parents:
                roots.append(p)
        repo = (mission or {}).get("repo") or ""
        if repo:
            roots.append(Path(repo))
        seen, scanned = set(), 0
        hidden = {str(Path(p).resolve()) for p in self.office.repos.hidden}
        for root in roots:
            if str(root) in seen:
                continue
            seen.add(str(root))
            for dirpath, dirs, files in os.walk(root, followlinks=False):
                dirs[:] = [d for d in dirs if d not in SECRET_PRUNE and not d.startswith(".")]
                for name in files:
                    if scanned >= 5000 or len(out) >= limit * 4:
                        break
                    p = Path(dirpath, name)
                    if _is_secret(name) or p.suffix.lower() not in TEXT_SUFFIXES:
                        continue
                    try:
                        if str(p.resolve()) in hidden or p.stat().st_size > 2_000_000:
                            continue
                        text = p.read_text(errors="replace")
                    except OSError:
                        continue
                    scanned += 1
                    score = _hit(terms, text)
                    if score:
                        line = next((i for i, x in enumerate(text.splitlines(), 1)
                                     if any(t in x.lower() for t in terms)), 1)
                        try:
                            ref = str(p.relative_to(COMPANY)) if COMPANY in p.resolve().parents else str(p)
                        except ValueError:
                            ref = str(p)
                        out.append({"kind": "file", "ref": f"{ref}:{line}", "title": p.name,
                                    "snippet": _snippet(terms, text), "score": score})
        out.sort(key=lambda x: (-x["score"], x["kind"], x["title"]))
        return {"query": query, "mission_id": int(mission_id) if mission_id else None,
                "results": out[:max(1, min(int(limit), 100))], "scanned_files": scanned}
