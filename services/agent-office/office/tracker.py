"""Agent activity from the office's own records: what each agent is doing, did, and how long it took.

The timelines come from the event journal (office/activity.py has the rules); tasks, missions and the inbox
from the store; tokens from the ledger. Nothing here writes. server.py serves it as /api/activity/...,
and office/reports.py builds the standup and the evening summary from `period`.
"""
import datetime as dt
import os
import time
from zoneinfo import ZoneInfo

from . import activity as A
from . import events as E
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
            mission = self._mission_brief(task["mission_id"]) if task and task.get("mission_id") else None
            queued = self.store.next_queued(aid)
            open_items = self.o.journal.inbox(state="NEEDS_ATTENTION,IN_PROGRESS", agent=aid, limit=20)["items"]
            state, label = A.desk_state(st["status"], st.get("in_meeting"), open_items)
            secrets = tuple(self.o.journal.secrets())
            recent = self.db.execute(
                "SELECT kind, text, ts, task_id FROM events WHERE agent=? AND kind NOT IN ('think','start') "
                "ORDER BY id DESC LIMIT 3", (aid,)).fetchall()
            out.append({
                "id": aid, "name": cfg["name"], "role": cfg["role"], "status": st["status"],
                "state": state, "state_label": label, "in_meeting": bool(st.get("in_meeting")),
                "activity": E.redact(st.get("activity", ""), secrets), "activity_ts": st.get("activity_ts"),
                "task": _task_brief(task) if task else None,
                # what the run has done so far: tool steps recorded for it (a count, not a share of the work)
                "actions": self._actions(task["id"], run_start) if task else 0,
                "mission": mission,
                "running_since": run_start, "running_s": round(now - run_start, 1) if run_start else 0,
                "queued": [_task_brief(t) for t in queued[:10]], "queued_count": len(queued),
                "blockers": [{k: i[k] for k in ("id", "kind", "title", "priority", "state")} for i in open_items],
                "recent": [dict(r, text=E.redact(r["text"], secrets)) for r in recent],
                "active_24h_s": summary.get(aid, {}).get("active_s", 0),
                "runs_24h": summary.get(aid, {}).get("runs", 0),
                "estimated": summary.get(aid, {}).get("estimated", False),
            })
        return out

    def _actions(self, tid, since):
        return self.db.execute(
            "SELECT COUNT(*) FROM events WHERE task_id=? AND kind NOT IN ('think','start','done','assign','info') "
            "AND ts>=?", (tid, since or 0)).fetchone()[0]

    def _mission_brief(self, mid):
        """A mission and how far it is: its tasks done out of all its tasks so far (the plan can still grow)."""
        m = self.store.mission(mid)
        if not m:
            return None
        counts = dict(self.db.execute("SELECT status, COUNT(*) FROM tasks WHERE mission_id=? GROUP BY status", (mid,)))
        verdicts = m.get("verdicts") or []
        return {"id": m["id"], "title": m["title"], "status": m["status"], "total_tasks": sum(counts.values()),
                "done_tasks": counts.get("done", 0), "failed_tasks": counts.get("failed", 0),
                "running_tasks": counts.get("running", 0), "criteria": len(m.get("criteria") or []),
                "passed": sum(1 for v in verdicts if v.get("verdict") == "PASS"),
                "created_at": m["created_at"], "started_at": m["started_at"], "finished_at": m["finished_at"]}

    def board(self, now=None):
        """The office's work as a Jira-style board (Mario Home's Agents tab): to do in the order it will run, in
        progress with how long it has run, what needs you (open inbox items), and what finished today."""
        now = now or time.time()
        ov = self.overview(now)
        day = ov["day_start"]
        live = {a["task"]["id"]: a for a in ov["agents"] if a["task"]}
        tl = self.timelines(day, now, now)
        titles = {}

        def mission(mid):
            if mid and mid not in titles:
                m = self.store.mission(mid)
                titles[mid] = m["title"] if m else ""
            return titles.get(mid, "") if mid else ""

        def card(t, **extra):
            out = {k: t.get(k) for k in ("id", "title", "agent", "status", "project", "mission_id", "created_by",
                                         "attempts", "depends_on", "created_at", "started_at", "finished_at")}
            out["mission"] = mission(t.get("mission_id"))
            return {**out, **extra}

        queued = sorted(self.store.tasks(status="queued", limit=500), key=lambda t: t["id"])
        todo = [card(t) for t in queued[:100]]
        doing = []
        for t in self.store.tasks(status="running", limit=200):
            a = live.get(t["id"]) or {}
            doing.append(card(t, running_since=a.get("running_since") or t.get("started_at"),
                              actions=a.get("actions", 0), last=((a.get("recent") or [{}])[0]).get("text", "")))   # redacted above
        needs = []
        for i in self.o.journal.inbox(state="NEEDS_ATTENTION,IN_PROGRESS", limit=100)["items"]:
            t = self.store.task(i["task_id"]) if i.get("task_id") else None
            needs.append({"inbox_id": i["id"], "kind": i["kind"], "priority": i["priority"], "state": i["state"],
                          "reason": i["title"], "agent": i.get("agent") or (t or {}).get("agent", ""),
                          "since": i["created_at"], "task": card(t) if t else None,
                          "mission": mission(i.get("mission_id"))})
        done = []
        for r in self.db.execute("SELECT * FROM tasks WHERE finished_at>=? AND finished_at<=? AND "
                                 "status IN ('done','failed','cancelled') ORDER BY finished_at DESC LIMIT 60", (day, now)):
            t = dict(r)
            x = tl.get(t["id"])
            run = A.seconds(A.clip(x["runs"], day, now)) if x else 0
            done.append(card(t, run_s=round(run, 1), estimated=bool(x and x.get("estimated"))))
        agents = [{k: a[k] for k in ("id", "name", "role", "state", "state_label", "running_since", "actions",
                                     "queued_count", "active_24h_s")}
                  | {"task": {"id": a["task"]["id"], "title": a["task"]["title"]} if a["task"] else None,
                     "needs_you": len(a["blockers"])} for a in ov["agents"]]
        return {"day_start": day, "timezone": ov["timezone"], "agents": agents, "counts": ov["counts"],
                "inbox": ov["inbox"], "columns": {"todo": todo, "doing": doing, "needs_you": needs, "done": done},
                "todo_total": len(queued)}

    def overview(self, now=None):
        """One picture of the office for every view: the desks (Virtual Office), the dashboard (Command Center)
        and the phone all read this, so they always agree."""
        now = now or time.time()
        tz = self.o.reports.s["timezone"]          # "today" is the reports' day (Asia/Kolkata by default)
        day = dt.datetime.fromtimestamp(now, ZoneInfo(tz)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        agents = self.assignments(now)
        today = dict(self.db.execute(
            "SELECT status, COUNT(*) FROM tasks WHERE finished_at>=? AND finished_at<=? GROUP BY status", (day, now)))
        tasks = dict(self.db.execute("SELECT status, COUNT(*) FROM tasks WHERE status IN ('queued','running') "
                                     "GROUP BY status"))
        missions = dict(self.db.execute("SELECT status, COUNT(*) FROM missions GROUP BY status"))
        shown = [r[0] for r in self.db.execute(
            "SELECT id FROM missions WHERE status IN ('queued','running','unverified') OR finished_at>=? "
            "ORDER BY id DESC LIMIT 12", (now - 7 * 86400,))]
        by_state = {k: 0 for k in A.DESK_STATES}
        for a in agents:
            by_state[a["state"]] += 1
        return {
            "now": now, "day_start": day, "timezone": tz,
            "agents": agents,
            "counts": {
                "agents": len(agents), "active": by_state["working"], "idle": by_state["idle"],
                "blocked": by_state["blocked"], "error": by_state["error"], "paused": by_state["paused"],
                "running_tasks": tasks.get("running", 0), "queued_tasks": tasks.get("queued", 0),
                "done_today": today.get("done", 0), "failed_today": today.get("failed", 0),
                "cancelled_today": today.get("cancelled", 0),
                "running_missions": missions.get("running", 0), "queued_missions": missions.get("queued", 0),
            },
            "inbox": self.o.journal.counts(),
            "missions": [m for m in (self._mission_brief(mid) for mid in shown) if m],
            "active_24h_s": round(sum(a["active_24h_s"] for a in agents), 1),
            "estimated": any(a["estimated"] for a in agents),
        }

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
