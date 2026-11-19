"""What happened in the office, as events: pure rules with no database in them (office/journal.py keeps them).

A status change of a task or mission becomes zero or more events. Each event says what it means for the
Action Inbox (open an issue, mark one in progress, resolve one) and whether it is worth a notification. The
rules are here, apart from storage, so scripts/verify-agent-office.sh can check every one directly.

Event fields: type, severity (info | warning | high | critical), agent, task_id, mission_id, text, evidence
(list of references such as "task:12"), dedup (the same fact twice is one event).
"""
import hashlib
import json
import re

SEVERITIES = ("info", "warning", "high", "critical")
PRIORITIES = ("normal", "high", "critical")
NEEDS, WORKING, RESOLVED = "NEEDS_ATTENTION", "IN_PROGRESS", "RESOLVED"
STATES = (NEEDS, WORKING, RESOLVED)

# event type -> (notification priority or None, group for grouped delivery or None)
NOTIFY = {
    "task.failed": ("high", None),
    "task.blocked": ("high", None),
    "approval.requested": ("critical", None),
    "quota.exceeded": ("high", None),
    "limit.reached": ("high", None),
    "office.error": ("high", None),
    "mission.failed": ("high", None),
    "mission.unverified": ("normal", None),
    "mission.completed": ("normal", "office.missions"),
    "task.completed": ("normal", "office.done"),
    "report.ready": ("normal", "office.reports"),
}

# which events open an issue, and its inbox kind
OPENS = {
    "task.failed": "failed", "task.blocked": "blocked", "mission.failed": "mission-failed",
    "mission.unverified": "mission-unverified", "approval.requested": "approval", "quota.exceeded": "quota",
    "limit.reached": "limit", "office.error": "error",
}


def task_issue(tid):
    return f"task:{tid}"


def mission_issue(mid):
    return f"mission:{mid}"


def _ev(type_, severity, text, row, dedup, agent=None, task_id=None, mission_id=None, evidence=None):
    return {"type": type_, "severity": severity, "text": text[:1000], "dedup": dedup,
            "agent": agent if agent is not None else row.get("agent"), "task_id": task_id,
            "mission_id": mission_id, "evidence": evidence or []}


def task_events(old, new, resumed=False, name=None):
    """Events for one task write. old is None for a new task; resumed: it continues interrupted work."""
    tid, st = new["id"], new["status"]
    who = name or new.get("agent") or ""
    mid = new.get("mission_id")
    label = f"#{tid} {new.get('title', '')}".strip()
    ev = lambda t, sev, text, key, **kw: _ev(t, sev, text, new, f"{t}:{tid}:{key}", task_id=tid, mission_id=mid,
                                              evidence=[f"task:{tid}"] + ([f"mission:{mid}"] if mid else []), **kw)
    if old is None:
        return [ev("task.created", "info", f"{who} was given task {label}", new.get("created_at") or 0)]
    was = old["status"]
    if was == st:
        return []
    started, finished = new.get("started_at") or 0, new.get("finished_at") or 0
    if st == "running":
        if resumed or (new.get("attempts") or 0) > 1:
            return [ev("task.resumed", "info", f"{who} resumed task {label}", started)]
        return [ev("task.started", "info", f"{who} started task {label}", started)]
    if st == "done":
        return [ev("task.completed", "info", f"{who} finished task {label}", f"{finished}:{new.get('attempts')}")]
    if st == "cancelled":
        return [ev("task.cancelled", "info", f"Task {label} was cancelled", f"{finished}:{new.get('attempts')}")]
    if st == "failed":
        err = (new.get("error") or "").strip()
        if err.startswith("blocked:"):
            return [ev("task.blocked", "high", f"{who} is blocked on task {label}: {err[8:].strip()}",
                       f"{finished}:{new.get('attempts')}")]
        return [ev("task.failed", "high", f"{who} could not finish task {label}" + (f": {err}" if err else ""),
                   f"{finished}:{new.get('attempts')}")]
    if st in ("queued", "blocked") and was in ("failed", "cancelled"):
        return [ev("task.requeued", "info", f"Task {label} is queued again for {who}", old.get("finished_at") or 0)]
    if st == "queued" and was == "running":
        # a transient failure keeps the attempt and records a new error; a pause, quota stop or restart gives
        # the attempt back or leaves the error as it was
        err = (new.get("error") or "").strip()
        if err and err != (old.get("error") or "").strip() and new.get("attempts") == old.get("attempts"):
            return [ev("task.retry", "warning", f"{who} hit a problem on task {label} and will try again: {err}",
                       f"{started}:{new.get('attempts')}")]
        return [ev("task.interrupted", "info", f"Task {label} was interrupted and waits to continue", started)]
    return []


def mission_events(old, new):
    mid, st = new["id"], new["status"]
    label = f"#{mid} {new.get('title', '')}".strip()
    ev = lambda t, sev, text, key: _ev(t, sev, text, new, f"{t}:{mid}:{key}", agent="", mission_id=mid,
                                        evidence=[f"mission:{mid}"])
    if old is None:
        return [ev("mission.created", "info", f"Mission {label} was created", new.get("created_at") or 0)]
    was = old["status"]
    if was == st:
        return []
    done = new.get("finished_at") or 0
    if st == "running" and was == "queued":
        return [ev("mission.started", "info", f"Mission {label} started", new.get("started_at") or 0)]
    if st == "succeeded":
        return [ev("mission.completed", "info", f"Mission {label} succeeded: every criterion passed", done)]
    if st == "failed":
        err = (new.get("error") or "").strip()
        e = ev("mission.failed", "high", f"Mission {label} failed" + (f": {err}" if err else ""), done)
        if any(t.get("status") == "failed" for t in new.get("tasks") or []):
            e["quiet"] = True       # its failed task already has the inbox item and the alert: one problem, one item
        return [e]
    if st == "unverified":
        return [ev("mission.unverified", "warning", f"Mission {label} finished without a verdict for every "
                                                    "criterion; check its report", done)]
    if st == "cancelled":
        return [ev("mission.cancelled", "info", f"Mission {label} was cancelled", done)]
    if st in ("queued", "running") and was in ("failed", "unverified", "cancelled", "succeeded"):
        return [ev("mission.reopened", "info", f"Mission {label} has work again", old.get("finished_at") or 0)]
    return []


def issue_effect(event):
    """What an event does to the Action Inbox: (action, issue key, kind) or None.

    open      the issue needs attention (a resolved one is reopened)
    progress  someone is working on it again (an operator retry, a resumed task)
    resolve   the condition has cleared (the task finished, or was cancelled)
    """
    t = event["type"]
    if event.get("quiet"):
        return None
    if t in OPENS:
        if t.startswith("task."):
            return "open", task_issue(event["task_id"]), OPENS[t]
        if t.startswith("mission."):
            return "open", mission_issue(event["mission_id"]), OPENS[t]
        return "open", event["issue"], OPENS[t]
    if t in ("task.requeued", "task.resumed"):
        return "progress", task_issue(event["task_id"]), None
    if t in ("task.completed", "task.cancelled"):
        return "resolve", task_issue(event["task_id"]), None
    if t == "mission.reopened":
        return "progress", mission_issue(event["mission_id"]), None
    if t in ("mission.completed", "mission.cancelled"):
        return "resolve", mission_issue(event["mission_id"]), None
    if t in ("quota.restored", "limit.cleared", "approval.granted", "approval.declined"):
        return "resolve", event["issue"], None
    return None


def notification_for(event):
    """(priority, group) when the event is worth telling the owner about, else None."""
    return None if event.get("quiet") else NOTIFY.get(event["type"])


def transition(state, action):
    """The inbox state after a manual action, or raises ValueError. Conditions are checked by the caller."""
    nxt = {("ack", NEEDS): WORKING, ("ack", WORKING): WORKING,
           ("resolve", NEEDS): RESOLVED, ("resolve", WORKING): RESOLVED,
           ("dismiss", NEEDS): RESOLVED, ("dismiss", WORKING): RESOLVED,
           ("reopen", RESOLVED): NEEDS}.get((action, state))
    if not nxt:
        raise ValueError(f"cannot {action} an item that is {state}")
    return nxt


def request_key(kind, ref, request):
    """The identity of an approval request: the same request asked twice is one inbox item."""
    raw = json.dumps([kind, str(ref), request], sort_keys=True)
    return "approval:" + hashlib.sha256(raw.encode()).hexdigest()[:16]


# What never goes into an event or a notification: anything shaped like a credential.
_SECRET = re.compile(
    r"(-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----"
    r"|\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}"
    r"|\bsk-ant-[A-Za-z0-9_-]{10,}"
    r"|\bAIza[0-9A-Za-z_-]{30,}"
    r"|\bgh[pousr]_[A-Za-z0-9]{20,}"
    r"|\bglpat-[A-Za-z0-9_-]{20,}"
    r"|\bxox[abprs]-[A-Za-z0-9-]{10,}"
    r"|\bya29\.[0-9A-Za-z_-]{20,}"
    r"|\bAKIA[0-9A-Z]{16}"
    r"|(?i:bearer)\s+[A-Za-z0-9._~+/-]{16,}=*"
    r"|(?i:(?:api[_-]?key|token|secret|password|passwd)\s*[=:]\s*)[^\s'\"]{6,})", re.S)


def redact_tree(value, extra=()):
    """redact() through every string of a JSON-like value (a report's data), keys and structure kept."""
    if isinstance(value, str):
        return redact(value, extra)
    if isinstance(value, dict):
        return {k: redact_tree(v, extra) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_tree(v, extra) for v in value]
    return value


def redact(text, extra=()):
    """text with credential-shaped strings (and any of extra, e.g. the operator key) replaced."""
    text = str(text or "")
    for s in extra:
        if s and len(s) >= 8:
            text = text.replace(s, "[redacted]")
    return _SECRET.sub("[redacted]", text)
