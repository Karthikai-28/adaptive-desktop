"""Agent activity from the office's own records: what each agent is doing, did, and how long it took.

The timelines come from the event journal (office/activity.py has the rules); tasks, missions and the inbox
from the store; tokens from the ledger. Nothing here writes. server.py serves it as /api/activity/...,
and office/reports.py builds the standup and the evening summary from `period`.
"""
import os
import time

from . import activity as A
from .config import COMPANY

LOOKBACK_S = 14 * 86400        # how far back a timeline looks for a task's queue or run start
TERMINAL = ("done", "failed", "cancelled")


def _task_brief(t):
    return {k: t.get(k) for k in ("id", "agent", "title", "status", "project", "mission_id", "created_by",
                                  "depends_on", "attempts", "created_at", "started_at", "finished_at")}


class Tracker:
    def __init__(self, office):
        self.o = office
        self.store = office.store
        self.db = office.store.db

    # ------------------------------------------------------------------ timelines
    def timelines(self, a, b, now=None):
        """Task timelines that touch [a, b): from the journal, plus estimated ones for work it never saw."""
        now = now or time.time()
        rows = [dict(r) for r in self.db.execute(
            "SELECT seq, ts, type, agent, task_id, mission_id FROM event_log WHERE type LIKE 'task.%' AND ts>=? AND "
            "ts<? ORDER BY seq", (a - LOOKBACK_S, b))]
        tl = A.task_timelines(rows, min(now, b))
        seen = set(tl)
        for t in self.db.execute(
                "SELECT * FROM tasks WHERE started_at IS NOT NULL AND started_at<? AND "
                "(finished_at IS NULL OR finished_at>=?)", (b, a)):
            t = dict(t)
            if t["id"] in seen or self._has_events(t["id"]):
                continue
            est = A.estimated_timeline(t, min(now, b))
            if est:
                tl[t["id"]] = est
        return tl

    def _has_events(self, tid):
        return self.db.execute("SELECT 1 FROM event_log WHERE task_id=? LIMIT 1", (tid,)).fetchone() is not None

    def task_timing(self, tid, now=None):
        now = now or time.time()
        t = self.store.task(tid)
        if not t:
            return None
        rows = [dict(r) for r in self.db.execute(
            "SELECT seq, ts, type, agent, task_id, mission_id FROM event_log WHERE task_id=? ORDER BY seq", (tid,))]
        tl = A.task_timelines(rows, now).get(tid) or A.estimated_timeline(t, now) or \
            {"agent": t["agent"], "mission_id": t["mission_id"], "runs": [], "queued": [], "running": False,
             "estimated": False}
        approvals = A.approval_waits(self.o.journal.inbox(kind="approval", task_id=tid, limit=200)["items"], now)
        return {"task": _task_brief(t), "runs": tl["runs"], "queued": tl["queued"], "estimated": tl["estimated"],
                "run_s": round(A.seconds(tl["runs"]), 1), "queue_s": round(A.seconds(tl["queued"]), 1),
                "approval_s": round(A.seconds(approvals), 1), "attempts": t["attempts"]}

    # ------------------------------------------------------------------ now
    def assignments(self, now=None):
        """Every agent: status, current task and mission, when this run started, what is queued next."""
        now = now or time.time()
        out = []
        day = now - 86400
        tl = self.timelines(day, now, now)
        summary = A.agent_summary(tl, day, now, list(self.o.agents))
        for aid, cfg in self.o.agents.items():
            st = self.o.agent_state(aid)
            cur = st.get("task") or None
            task = self.store.task(cur["id"]) if cur else None
            run_start = None
            if task and task["id"] in tl and tl[task["id"]]["running"]:
                run_start = tl[task["id"]]["runs"][-1][0]
            elif task:
                run_start = task.get("started_at")
            mission = self.store.mission(task["mission_id"]) if task and task.get("mission_id") else None
            queued = self.store.next_queued(aid)
            open_items = self.o.journal.inbox(state="NEEDS_ATTENTION,IN_PROGRESS", agent=aid, limit=20)["items"]
            out.append({
                "id": aid, "name": cfg["name"], "role": cfg["role"], "status": st["status"],
                "activity": st.get("activity", ""), "activity_ts": st.get("activity_ts"),
                "task": _task_brief(task) if task else None,
                "mission": {k: mission[k] for k in ("id", "title", "status")} if mission else None,
                "running_since": run_start, "running_s": round(now - run_start, 1) if run_start else 0,
                "queued": [_task_brief(t) for t in queued[:10]], "queued_count": len(queued),
                "blockers": [{k: i[k] for k in ("id", "kind", "title", "priority", "state")} for i in open_items],
                "active_24h_s": summary.get(aid, {}).get("active_s", 0),
            })
        return out

    # ------------------------------------------------------------------ a period
    def history(self, a, b, agent=None, limit=200, now=None):
        """Per task that ran or waited in [a, b): who, what, how it ended, run and queue time inside the window."""
        now = now or time.time()
        out = []
        for tid, t in self.timelines(a, b, now).items():
            if agent and t["agent"] != agent:
                continue
            runs, queued = A.clip(t["runs"], a, b), A.clip(t["queued"], a, b)
            if not runs and not queued:
                continue
            task = self.store.task(tid) or {}
            out.append({"task": _task_brief(task) if task else {"id": tid}, "agent": t["agent"],
                        "mission_id": t["mission_id"], "runs": runs, "run_s": round(A.seconds(runs), 1),
                        "queue_s": round(A.seconds(queued), 1), "estimated": t["estimated"],
                        "outcome": runs[-1][2] if runs else "queued"})
        out.sort(key=lambda r: -(r["runs"][-1][1] if r["runs"] else 0))
        return out[:max(1, min(int(limit), 1000))]

    def summary(self, a, b, now=None):
        now = now or time.time()
        tl = self.timelines(a, b, now)
        per = A.agent_summary(tl, a, b, list(self.o.agents))
        approvals = A.clip(A.approval_waits(self.o.journal.inbox(kind="approval", limit=200)["items"], now), a, b)
        for aid, row in per.items():
            row["name"] = self.o.agents.get(aid, {}).get("name", aid)
        return {"since": a, "until": b, "agents": list(per.values()),
                "approval_wait_s": round(A.seconds(approvals), 1), "approvals": len(approvals),
                "estimated": any(r["estimated"] for r in per.values())}

    def mission_progress(self, mid, now=None):
        now = now or time.time()
        m = self.store.mission(mid, with_tasks=True)
        if not m:
            return None
        counts = {}
        for t in m["tasks"]:
            counts[t["status"]] = counts.get(t["status"], 0) + 1
        a = min([t["created_at"] for t in m["tasks"] if t.get("created_at")] or [m["created_at"] or now])
        tl = {tid: x for tid, x in self.timelines(a, now, now).items() if x["mission_id"] == mid}
        per = A.agent_summary(tl, a, now)
        verdicts = m.get("verdicts") or []
        return {"mission": {k: m[k] for k in ("id", "title", "status", "risk", "created_at", "started_at",
                                              "finished_at", "error")},
                "tasks": counts, "total_tasks": len(m["tasks"]), "done_tasks": counts.get("done", 0),
                "criteria": len(m["criteria"]), "passed": sum(1 for v in verdicts if v.get("verdict") == "PASS"),
                "failed": sum(1 for v in verdicts if v.get("verdict") == "FAIL"),
                "contributions": [{"agent": aid, "name": self.o.agents.get(aid, {}).get("name", aid),
                                   "active_s": r["active_s"], "tasks": r["tasks"]} for aid, r in per.items()],
                "estimated": any(x["estimated"] for x in tl.values())}

    # ------------------------------------------------------------------ for the reports
    def tokens(self, a, b):
        """Tokens per person in [a, b) from the ledger; providers are subscriptions or local, so no money cost."""
        try:
            calls = [c for c in self.o.ledger.calls(a) if c["ts"] < b]
        except Exception:
            return {"available": False, "agents": {}, "total": 0}
        per = {}
        for c in calls:
            row = per.setdefault(c["agent"], {"total": 0, "fresh": 0, "cached": 0, "out": 0, "calls": 0})
            for k in ("fresh", "cached", "out"):
                row[k] += int(c.get(k) or 0)
            row["total"] += int(c.get("fresh") or 0) + int(c.get("cached") or 0) + int(c.get("out") or 0)
            row["calls"] += 1
        return {"available": True, "agents": per, "total": sum(r["total"] for r in per.values()),
                "calls": len(calls)}

    def files_changed(self, a, b, limit=40):
        """Workspace files the team wrote in [a, b) (company/projects), newest first."""
        root = COMPANY / "projects"
        found = []
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", ".git")]
            for f in files:
                p = os.path.join(dirpath, f)
                try:
                    m = os.stat(p).st_mtime
                except OSError:
                    continue
                if a <= m < b:
                    found.append((m, os.path.relpath(p, COMPANY)))
            if len(found) > 5000:
                break
        return [{"path": p, "modified": m} for m, p in sorted(found, reverse=True)[:limit]]

    def period(self, a, b, now=None):
        """Everything a report about [a, b) needs, gathered once."""
        now = now or time.time()
        tasks = lambda q, args: [dict(r) for r in self.db.execute(q, args)]
        finished = tasks("SELECT * FROM tasks WHERE finished_at>=? AND finished_at<? ORDER BY finished_at", (a, b))
        running = self.store.tasks(status="running", limit=200)
        queued = sorted(self.store.tasks(status="queued", limit=500), key=lambda t: t["id"])
        evs = [dict(r) for r in self.db.execute(
            "SELECT seq, ts, type, agent, task_id, mission_id, text FROM event_log WHERE ts>=? AND ts<? ORDER BY seq",
            (a, b))]
        missions_touched = {m["id"]: m for m in (self.store.mission(r[0]) for r in self.db.execute(
            "SELECT id FROM missions WHERE status IN ('queued','running') OR (finished_at>=? AND finished_at<?) OR "
            "(created_at>=? AND created_at<?)", (a, b, a, b))) if m}
        open_items = self.o.journal.inbox(state="NEEDS_ATTENTION,IN_PROGRESS", limit=200)["items"]
        resolved = [dict(r) for r in self.db.execute(
            "SELECT id, issue, kind, title, resolution, resolved_at, task_id, agent FROM inbox WHERE resolved_at>=? "
            "AND resolved_at<?", (a, b))]
        return {
            "since": a, "until": b, "now": now,
            "agents": {aid: {"name": c["name"], "role": c["role"]} for aid, c in self.o.agents.items()},
            "summary": self.summary(a, b, now),
            "history": self.history(a, b, limit=1000, now=now),
            "finished": [dict(_task_brief(t), result=(t.get("result") or "")[:600], error=(t.get("error") or "")[:300])
                         for t in finished],
            "running": [_task_brief(t) for t in running],
            "queued": [_task_brief(t) for t in queued],
            "task_status": {t["id"]: t["status"] for t in queued + running + finished},
            "missions": [dict({k: m.get(k) for k in ("id", "title", "status", "created_at", "finished_at", "error")},
                              criteria=len(m.get("criteria") or []),
                              passed=sum(1 for v in m.get("verdicts") or [] if v.get("verdict") == "PASS"))
                         for m in missions_touched.values()],
            "retries": [e for e in evs if e["type"] == "task.retry"],
            "recovered": [r for r in resolved if r["resolution"] == "recovered"],
            "open_items": open_items,
            "tokens": self.tokens(a, b),
            "files": self.files_changed(a, b),
            "assignments": self.assignments(now) if b >= now - 120 else None,
        }
