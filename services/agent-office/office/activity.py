"""Who worked on what, and for how long: timelines from the event journal (pure, no database).

A task's time is split into what it was doing:
  run        an agent was working on it: from task.started/resumed to the next completed, failed, blocked,
             cancelled, retry or interrupted event
  queue      waiting for its turn: from created, requeued, retry or interrupted to the next start
  approval   waiting for the operator: an approval request (inbox) from requested to granted/declined
An agent's active time is the union of its run intervals, so overlapping intervals are never counted twice;
its idle time is the rest of the window.

Work finished before the journal existed has no events. For it the task's own started_at/finished_at give
one interval, marked estimated (it covers only the last attempt and includes any pause inside it).
"""

RUN_START = {"task.started", "task.resumed"}
RUN_END = {"task.completed": "done", "task.failed": "failed", "task.blocked": "blocked",
           "task.cancelled": "cancelled", "task.retry": "retry", "task.interrupted": "interrupted"}
QUEUE_START = {"task.created", "task.requeued", "task.retry", "task.interrupted"}
QUEUE_END = {"task.started", "task.resumed", "task.completed", "task.failed", "task.blocked", "task.cancelled"}


def task_timelines(events, now):
    """{task_id: {"agent", "mission_id", "runs": [[start, end, outcome]], "queued": [[start, end]], "running"}}
    from journal events (any order). An interval still open ends at `now` with outcome "running"/None."""
    out = {}
    for e in sorted(events, key=lambda e: e["seq"]):
        tid, typ = e.get("task_id"), e["type"]
        if not tid or not typ.startswith("task."):
            continue
        t = out.setdefault(tid, {"agent": e.get("agent") or "", "mission_id": e.get("mission_id"), "runs": [],
                                 "queued": [], "_run": None, "_queue": None, "estimated": False})
        if e.get("agent"):
            t["agent"] = e["agent"]
        ts = e["ts"]
        if typ in QUEUE_END and t["_queue"] is not None:
            t["queued"].append([t["_queue"], ts])
            t["_queue"] = None
        if typ in RUN_END and t["_run"] is not None:
            t["runs"].append([t["_run"], ts, RUN_END[typ]])
            t["_run"] = None
        if typ in RUN_START:
            t["_run"] = ts
        if typ in QUEUE_START:
            t["_queue"] = ts
    for t in out.values():
        t["running"] = t["_run"] is not None
        if t["_run"] is not None:
            t["runs"].append([t["_run"], now, "running"])
        if t["_queue"] is not None:
            t["queued"].append([t["_queue"], now])
        del t["_run"], t["_queue"]
    return out


def estimated_timeline(task, now):
    """One interval from a task row, for work the journal never saw."""
    s, f = task.get("started_at"), task.get("finished_at")
    if not s:
        return None
    end = f or (now if task.get("status") == "running" else None)
    if not end or end < s:
        return None
    outcome = "running" if not f else {"done": "done", "failed": "failed", "cancelled": "cancelled"}.get(
        task.get("status"), task.get("status"))
    queued = [[task["created_at"], s]] if task.get("created_at") and task["created_at"] <= s else []
    return {"agent": task.get("agent") or "", "mission_id": task.get("mission_id"), "runs": [[s, end, outcome]],
            "queued": queued, "running": not f and task.get("status") == "running", "estimated": True}


def clip(intervals, a, b):
    """The parts of [start, end, ...] intervals inside [a, b)."""
    out = []
    for iv in intervals:
        s, e = max(iv[0], a), min(iv[1], b)
        if e > s:
            out.append([s, e, *iv[2:]])
    return out


def union_seconds(intervals):
    total, cur_s, cur_e = 0.0, None, None
    for s, e, *_ in sorted(intervals):
        if cur_e is None or s > cur_e:
            if cur_e is not None:
                total += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None:
        total += cur_e - cur_s
    return total


def seconds(intervals):
    return sum(iv[1] - iv[0] for iv in intervals)


def approval_waits(items, now):
    """[start, end, item id] per approval item from its created_at to resolved_at (or now)."""
    return [[i["created_at"], i.get("resolved_at") or now, i["id"]] for i in items
            if i.get("kind") == "approval" and i.get("created_at")]


def agent_summary(timelines, a, b, agents=()):
    """Per agent, within [a, b): active (union of run time), idle, queue time of their tasks, and each task's
    own run time. Every agent in `agents` appears, even with nothing."""
    span = max(0.0, b - a)
    out = {aid: {"agent": aid, "active_s": 0.0, "idle_s": span, "queue_s": 0.0, "runs": 0, "tasks": {},
                 "estimated": False} for aid in agents}
    runs_by = {}
    for tid, t in timelines.items():
        aid = t["agent"]
        if not aid:
            continue
        row = out.setdefault(aid, {"agent": aid, "active_s": 0.0, "idle_s": span, "queue_s": 0.0, "runs": 0,
                                   "tasks": {}, "estimated": False})
        runs = clip(t["runs"], a, b)
        row["queue_s"] += seconds(clip(t["queued"], a, b))
        if runs:
            row["runs"] += len(runs)
            row["tasks"][tid] = round(seconds(runs), 1)
            row["estimated"] = row["estimated"] or t.get("estimated", False)
            runs_by.setdefault(aid, []).extend(runs)
    for aid, row in out.items():
        row["active_s"] = round(union_seconds(runs_by.get(aid, [])), 1)
        row["idle_s"] = round(max(0.0, span - row["active_s"]), 1)
        row["queue_s"] = round(row["queue_s"], 1)
    return out


def fmt_duration(s):
    s = int(round(s or 0))
    if s < 60:
        return f"{s}s"
    m = s // 60
    if m < 60:
        return f"{m}m"
    return f"{m // 60}h {m % 60:02d}m"


# ---------------------------------------------------------------------------------------------- desk status
# One word per agent, the same on the desktop (Virtual Office, Command Center) and on the phone.
DESK_STATES = ("working", "idle", "blocked", "error", "paused")
BLOCKING_KINDS = {"approval", "blocked", "limit", "quota"}
ERROR_KINDS = {"failed", "error", "mission-failed"}


def desk_state(status, in_meeting=False, items=()):
    """(state, label) for an agent from its live status and its open inbox items.

    What it is doing now wins: an agent at work is "working" even with an old failure open; the open items still
    show beside it. Otherwise an open blocker (an approval it waits for, a blocked task, a limit) makes it
    "blocked", an unhandled failure "error", and nothing at all "idle"."""
    open_kinds = {i.get("kind") for i in items if i.get("state") != "RESOLVED"}
    if status == "paused":
        return "paused", "Paused"
    if status == "quota":
        return "blocked", "Waiting for quota"
    if status == "working":
        return "working", "Working"
    if status == "thinking":
        return "working", "Replying"
    if in_meeting:
        return "working", "In a meeting"
    if "approval" in open_kinds:
        return "blocked", "Waiting for your decision"
    if open_kinds & BLOCKING_KINDS:
        return "blocked", "Blocked"
    if open_kinds & ERROR_KINDS:
        return "error", "Last task failed"
    return "idle", "Idle"
