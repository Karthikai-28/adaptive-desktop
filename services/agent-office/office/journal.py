"""The office's memory of what happened: an append-only event log, the Action Inbox and notifications.

Every task and mission status write goes through Store, which calls Journal._observe inside the same
transaction, so a status change and its event are stored together or not at all. The rules for what an event
means live in office/events.py; this module only keeps them.

- event_log      append-only (SQLite triggers refuse UPDATE and DELETE); seq is the order clients resume from
- inbox          one row per issue (a failed task, a pending approval, a quota stop); its state is the only
                 mutable part, and every change to it is itself an event in event_log
- notifications  one per event worth telling the owner, numbered for delivery; deliveries keeps how far each
                 channel (the phone through Adaptive Link) has confirmed

Acknowledging or resolving an inbox item never authorises anything: an approval is granted only by
server.py's approve route, which requires the operator key, and replays the stored request through the same
checks as a fresh one.
"""
import asyncio
import datetime as dt
import json
import time
import uuid

from . import events as E

INBOX_LIMIT = 200
LIMIT_WINDOW_S = 3600           # a per-hour limit clears an hour after it was last hit
TITLES = {
    "task.failed": "{who}: task #{task} failed",
    "task.blocked": "{who} is blocked on task #{task}",
    "task.completed": "{who} finished task #{task}",
    "mission.failed": "Mission #{mission} failed",
    "mission.unverified": "Mission #{mission} needs checking",
    "mission.completed": "Mission #{mission} succeeded",
    "approval.requested": "Approval needed",
    "quota.exceeded": "Quota used up",
    "limit.reached": "Limit reached",
    "office.error": "Office error",
}


def iso(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat(timespec="seconds") if ts else None


def log(level, msg, **kw):
    print(json.dumps({"log": "journal", "level": level, "msg": msg, **kw}, default=str), flush=True)


class Journal:
    def __init__(self, store, names=None, secrets=lambda: ()):
        self.store = store
        self.db = store.db
        self.names = names or {}            # agent id -> display name
        self.secrets = secrets              # strings that must never be stored (the operator key)
        self.publish = None                 # f(message) for the office's live socket, set by Office
        self.live_check = {}                # inbox kind -> f(item) -> bool, extra conditions (quota)
        self._new = None                    # asyncio.Event, set when a notification is added
        store.observers.append(self._observe)

    # ------------------------------------------------------------------ recording
    def _observe(self, kind, old, new):
        if kind == "task":
            resumed = bool(new["status"] == "running" and self.store.get(f"resume:{new['id']}"))
            evs = E.task_events(old, new, resumed, self.names.get(new.get("agent")))
        else:
            evs = E.mission_events(old, new)
        for ev in evs:
            self.record(ev)

    def record(self, ev, actor=""):
        """Store one event (once: a repeated dedup key is ignored) and apply what it means. Returns its row or None."""
        secrets = tuple(self.secrets())
        text = E.redact(ev.get("text", ""), secrets)
        now = time.time()
        with self.store.transaction():
            # looked up first: an ignored INSERT would still use up a sequence number and leave a gap
            if self.db.execute("SELECT 1 FROM event_log WHERE dedup=?", (ev["dedup"],)).fetchone():
                return None
            cur = self.db.execute(
                "INSERT INTO event_log(id,ts,type,severity,agent,task_id,mission_id,text,evidence,issue,"
                "actor,dedup) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, now, ev["type"], ev["severity"], ev.get("agent") or "", ev.get("task_id"),
                 ev.get("mission_id"), text, json.dumps(ev.get("evidence") or []), ev.get("issue") or "", actor,
                 ev["dedup"]))
            row = self.event(cur.lastrowid)
            quiet = bool(ev.get("quiet"))
            item = None if quiet else self._apply_issue(row, ev)
            note = None if quiet else self._notify(row, item)
        log("info", "event", seq=row["seq"], type=row["type"], task=row["task_id"], mission=row["mission_id"],
            inbox=item and item["id"], notification=note and note["id"])
        self._emit({"type": "journal", "event": row})
        if item:
            self._emit({"type": "inbox", "item": item, "counts": self.counts()})
        if note:
            self._emit({"type": "notification", "notification": note})
            if self._new is not None:
                self._new.set()
        return row

    def _emit(self, msg):
        if self.publish:
            try:
                self.publish(msg)
            except Exception as e:
                log("error", "publish failed", error=str(e))

    def _apply_issue(self, row, ev):
        eff = E.issue_effect({**ev, "task_id": row["task_id"], "mission_id": row["mission_id"]})
        if not eff:
            return None
        action, key, kind = eff
        item = self.item_by_issue(key)
        now = row["ts"]
        if action == "open":
            prio = (E.notification_for(row) or ("high", None))[0]
            if prio == "normal" and row["severity"] in ("high", "critical"):
                prio = "high"
            title = self._title(row)
            if item is None:
                cur = self.db.execute(
                    "INSERT INTO inbox(issue,kind,state,priority,title,text,agent,task_id,mission_id,request,first_seq,"
                    "last_seq,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (key, kind, E.NEEDS, prio, title, row["text"], row["agent"], row["task_id"], row["mission_id"],
                     json.dumps(ev["request"]) if ev.get("request") is not None else "", row["seq"], row["seq"],
                     now, now))
                return self.item(cur.lastrowid, history=False)
            reopen = item["state"] == E.RESOLVED
            self.db.execute(
                "UPDATE inbox SET state=?, kind=?, priority=?, title=?, text=?, last_seq=?, updated_at=?, "
                "generation=generation+?, resolved_at=CASE WHEN ? THEN NULL ELSE resolved_at END, "
                "resolved_by=CASE WHEN ? THEN '' ELSE resolved_by END, resolution=CASE WHEN ? THEN '' ELSE resolution END, "
                "acknowledged_at=CASE WHEN ? THEN NULL ELSE acknowledged_at END, "
                "request=CASE WHEN ?<>'' THEN ? ELSE request END WHERE id=?",
                (E.NEEDS, kind, prio, title, row["text"], row["seq"], now, 1 if reopen else 0, reopen, reopen, reopen,
                 reopen, json.dumps(ev["request"]) if ev.get("request") is not None else "",
                 json.dumps(ev["request"]) if ev.get("request") is not None else "", item["id"]))
            return self.item(item["id"], history=False)
        if item is None or item["state"] == E.RESOLVED:
            return None
        if action == "progress":
            if item["state"] != E.NEEDS:
                return None
            self.db.execute("UPDATE inbox SET state=?, last_seq=?, updated_at=? WHERE id=?",
                            (E.WORKING, row["seq"], now, item["id"]))
        else:
            resolution = {"task.completed": "recovered", "mission.completed": "recovered",
                          "task.cancelled": "cancelled", "mission.cancelled": "cancelled",
                          "approval.granted": "approved", "approval.declined": "declined"}.get(row["type"], "cleared")
            self.db.execute("UPDATE inbox SET state=?, last_seq=?, updated_at=?, resolved_at=?, resolved_by=?, "
                            "resolution=? WHERE id=?",
                            (E.RESOLVED, row["seq"], now, now, row["actor"] or "office", resolution, item["id"]))
        return self.item(item["id"], history=False)

    def _title(self, row):
        who = self.names.get(row["agent"]) or row["agent"] or "An agent"
        return TITLES.get(row["type"], row["type"]).format(who=who, task=row["task_id"], mission=row["mission_id"])

    def _notify(self, row, item):
        rule = E.notification_for(row)
        if not rule:
            return None
        prio, group = rule
        cur = self.db.execute(
            "INSERT OR IGNORE INTO notifications(seq,priority,grp,title,text,agent,task_id,mission_id,inbox_id,"
            "created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (row["seq"], prio, group or "", self._title(row), row["text"], row["agent"], row["task_id"],
             row["mission_id"], item and item["id"], row["ts"]))
        return self.notification(cur.lastrowid) if cur.rowcount else None

    # ------------------------------------------------------------------ issues raised by the office itself
    def _generation(self, issue):
        item = self.item_by_issue(issue)
        if item is None:
            return 1, None
        return (item["generation"] + 1 if item["state"] == E.RESOLVED else item["generation"]), item

    def raise_issue(self, type_, issue, text, severity="high", agent="", task_id=None, mission_id=None,
                    request=None, actor=""):
        """Open (or keep open) an issue the office noticed itself: a quota stop, a limit, an error, an approval.
        While it stays open, raising it again records nothing and notifies nobody."""
        gen, item = self._generation(issue)
        ev = {"type": type_, "severity": severity, "text": text, "agent": agent, "task_id": task_id,
              "mission_id": mission_id, "issue": issue, "dedup": f"{type_}:{issue}:{gen}", "request": request,
              "evidence": [f"inbox:{issue}"] + ([f"task:{task_id}"] if task_id else [])
              + ([f"mission:{mission_id}"] if mission_id else [])}
        self.record(ev, actor)
        return self.item_by_issue(issue)

    def clear_issue(self, type_, issue, text, actor="office"):
        item = self.item_by_issue(issue)
        if not item or item["state"] == E.RESOLVED:
            return item
        self.record({"type": type_, "severity": "info", "text": text, "agent": item["agent"], "issue": issue,
                     "task_id": item["task_id"], "mission_id": item["mission_id"],
                     "dedup": f"{type_}:{issue}:{item['generation']}", "evidence": [f"inbox:{issue}"]}, actor)
        return self.item_by_issue(issue)

    def request_approval(self, kind, ref, request, requested_by, text, agent="", task_id=None, mission_id=None):
        """Record that something needs the operator's approval. The request is stored as data: only the
        operator-key approve route can carry it out, through the same checks as a fresh request."""
        issue = E.request_key(kind, ref, request)
        return self.raise_issue("approval.requested", issue, text, "critical", agent, task_id, mission_id,
                                {"kind": kind, "ref": ref, "request": request, "requested_by": requested_by},
                                actor=requested_by)

    def sweep(self):
        """Resolve issues whose condition has cleared by itself (a quota came back, an hourly limit passed)."""
        for item in self.inbox(state=f"{E.NEEDS},{E.WORKING}", kind="quota,limit", limit=INBOX_LIMIT)["items"]:
            if not self.live(item):
                self.clear_issue("quota.restored" if item["kind"] == "quota" else "limit.cleared", item["issue"],
                                 "Quota is available again" if item["kind"] == "quota" else "The limit has reset")

    # ------------------------------------------------------------------ the inbox
    def live(self, item):
        """Whether the condition behind an item still holds (then it can only be dismissed, with the key)."""
        k = item["kind"]
        if k in self.live_check:
            return bool(self.live_check[k](item))
        if k in ("failed", "blocked"):
            t = self.store.task(item["task_id"]) if item["task_id"] else None
            return bool(t and t["status"] == "failed")
        if k in ("mission-failed", "mission-unverified"):
            m = self.store.mission(item["mission_id"]) if item["mission_id"] else None
            return bool(m and m["status"] in ("failed", "unverified"))
        if k == "approval":
            return item["state"] != E.RESOLVED
        if k == "limit":
            return time.time() - (self.event_ts(item["last_seq"]) or 0) < LIMIT_WINDOW_S
        return False

    def act(self, item_id, action, actor, note="", is_operator=False):
        """A person's action on an item: ack | resolve | dismiss | reopen | decline.

        ack marks it in progress and nothing else. resolve is refused while the condition holds (retry or
        cancel the task instead); dismiss closes it anyway and needs the operator key when it is still live.
        decline turns an approval request down. Approving is not here: see server.py."""
        item = self.item(item_id, history=False)
        if not item:
            raise LookupError("no such inbox item")
        if action == "decline":
            if item["kind"] != "approval" or item["state"] == E.RESOLVED:
                raise ValueError("only a pending approval request can be declined")
            return self.clear_issue("approval.declined", item["issue"], f"Declined by {actor}"
                                    + (f": {note}" if note else ""), actor)
        if item["kind"] == "approval" and action in ("resolve", "dismiss"):
            raise ValueError("an approval request is closed by approving it (operator key) or declining it")
        nxt = E.transition(item["state"], action)
        live = self.live(item) if action in ("resolve", "dismiss") else False
        if action == "resolve" and live:
            raise PermissionError("the problem is still there: retry or cancel the work, or dismiss the item "
                                  "with the operator key")
        if action == "dismiss" and live and not is_operator:
            raise PermissionError("dismissing a problem that is still there needs the operator key")
        now = time.time()
        with self.store.transaction():
            if action == "ack":
                self.db.execute("UPDATE inbox SET state=?, updated_at=?, acknowledged_at=COALESCE(acknowledged_at, ?), "
                                "acknowledged_by=CASE WHEN acknowledged_by='' THEN ? ELSE acknowledged_by END WHERE id=?",
                                (nxt, now, now, actor, item_id))
            elif action in ("resolve", "dismiss"):
                self.db.execute("UPDATE inbox SET state=?, updated_at=?, resolved_at=?, resolved_by=?, resolution=? "
                                "WHERE id=?", (nxt, now, now, actor, "dismissed" if action == "dismiss" else "resolved",
                                               item_id))
            else:   # reopen
                self.db.execute("UPDATE inbox SET state=?, updated_at=?, generation=generation+1, resolved_at=NULL, "
                                "resolved_by='', resolution='', acknowledged_at=NULL, acknowledged_by='' WHERE id=?",
                                (nxt, now, item_id))
            past = {"ack": "acknowledged", "resolve": "resolved", "dismiss": "dismissed", "reopen": "reopened"}[action]
            row = self.record({"type": f"inbox.{past}", "severity": "info", "agent": item["agent"],
                               "task_id": item["task_id"], "mission_id": item["mission_id"], "issue": item["issue"],
                               "text": f"{item['title']}: {past} by {actor}" + (f" ({note})" if note else ""),
                               "dedup": f"inbox.{past}:{item_id}:{uuid.uuid4().hex}",
                               "evidence": [f"inbox:{item['issue']}"]}, actor)
            self.db.execute("UPDATE inbox SET last_seq=? WHERE id=?", (row["seq"], item_id))
        out = self.item(item_id, history=False)
        self._emit({"type": "inbox", "item": out, "counts": self.counts()})
        return out

    def approved(self, item_id, actor, result_ref):
        """Close an approval request after server.py carried it out with the operator key."""
        item = self.item(item_id, history=False)
        return self.clear_issue("approval.granted", item["issue"], f"Approved by {actor}; started {result_ref}", actor)

    @staticmethod
    def _item(row, request=False):
        d = dict(row)
        raw = d.pop("request", "")
        if request:
            d["request"] = json.loads(raw) if raw else None
        else:
            d["has_request"] = bool(raw)
        d["links"] = {k: v for k, v in (("task", d["task_id"]), ("mission", d["mission_id"])) if v}
        for k in ("created_at", "updated_at", "acknowledged_at", "resolved_at"):
            d[k + "_utc"] = iso(d[k])
        return d

    def item(self, item_id, history=True, request=False):
        row = self.db.execute("SELECT * FROM inbox WHERE id=?", (item_id,)).fetchone()
        if not row:
            return None
        d = self._item(row, request)
        if history:     # everything that happened to the issue: its task's or mission's events and inbox actions
            issue = row["issue"]
            if issue.startswith("task:"):
                q, args = "issue=? OR task_id=?", (issue, row["task_id"])
            elif issue.startswith("mission:"):
                q, args = "issue=? OR (mission_id=? AND task_id IS NULL)", (issue, row["mission_id"])
            else:
                q, args = "issue=?", (issue,)
            d["history"] = [self._event(r) for r in self.db.execute(
                f"SELECT * FROM event_log WHERE {q} ORDER BY seq LIMIT 500", args)]
            d["live"] = self.live(d)
        return d

    def item_by_issue(self, issue):
        row = self.db.execute("SELECT * FROM inbox WHERE issue=?", (issue,)).fetchone()
        return self._item(row) if row else None

    def inbox(self, state=None, kind=None, agent=None, task_id=None, mission_id=None, priority=None, limit=50,
              offset=0):
        q, args = " FROM inbox WHERE 1=1", []
        for col, val in (("state", state), ("kind", kind), ("priority", priority)):
            if val:
                vals = [v.strip() for v in str(val).split(",") if v.strip()]
                q += f" AND {col} IN ({','.join('?' * len(vals))})"
                args += vals
        for col, val in (("agent", agent), ("task_id", task_id), ("mission_id", mission_id)):
            if val not in (None, ""):
                q += f" AND {col}=?"
                args.append(val)
        total = self.db.execute("SELECT COUNT(*)" + q, args).fetchone()[0]
        rows = self.db.execute(
            "SELECT *" + q + " ORDER BY CASE state WHEN 'NEEDS_ATTENTION' THEN 0 WHEN 'IN_PROGRESS' THEN 1 ELSE 2 END, "
            "CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 ELSE 2 END, updated_at DESC, id DESC LIMIT ? OFFSET ?",
            args + [max(1, min(int(limit), INBOX_LIMIT)), max(0, int(offset))]).fetchall()
        return {"items": [self._item(r) for r in rows], "total": total, "offset": offset, "counts": self.counts()}

    def counts(self):
        out = {s: 0 for s in E.STATES}
        for state, n in self.db.execute("SELECT state, COUNT(*) FROM inbox GROUP BY state"):
            out[state] = n
        out["critical"] = self.db.execute(
            "SELECT COUNT(*) FROM inbox WHERE state<>'RESOLVED' AND priority='critical'").fetchone()[0]
        return out

    # ------------------------------------------------------------------ the event log
    @staticmethod
    def _event(row):
        d = dict(row)
        d["evidence"] = json.loads(d["evidence"] or "[]")
        d["ts_utc"] = iso(d["ts"])
        return d

    def event(self, seq):
        row = self.db.execute("SELECT * FROM event_log WHERE seq=?", (seq,)).fetchone()
        return self._event(row) if row else None

    def event_ts(self, seq):
        row = self.db.execute("SELECT ts FROM event_log WHERE seq=?", (seq,)).fetchone() if seq else None
        return row[0] if row else None

    def head(self):
        return self.db.execute("SELECT COALESCE(MAX(seq),0) FROM event_log").fetchone()[0]

    def events(self, after=0, limit=200, type=None, agent=None, task_id=None, mission_id=None, since=None,
               until=None):
        """Events after a sequence number, oldest first: what a reconnecting client missed."""
        q, args = "SELECT * FROM event_log WHERE seq>?", [int(after)]
        if type:
            types = [t.strip() for t in type.split(",") if t.strip()]
            q += " AND (" + " OR ".join("type LIKE ?" for _ in types) + ")"
            args += [t.replace("*", "%") for t in types]
        for col, val in (("agent", agent), ("task_id", task_id), ("mission_id", mission_id)):
            if val not in (None, ""):
                q += f" AND {col}=?"
                args.append(val)
        if since:
            q += " AND ts>=?"; args.append(float(since))
        if until:
            q += " AND ts<?"; args.append(float(until))
        q += " ORDER BY seq LIMIT ?"
        args.append(max(1, min(int(limit), 1000)))
        rows = [self._event(r) for r in self.db.execute(q, args)]
        return {"events": rows, "head": self.head(), "more": len(rows) == max(1, min(int(limit), 1000))}

    # ------------------------------------------------------------------ notifications
    @staticmethod
    def _note(row):
        d = dict(row)
        d["group"] = d.pop("grp") or None
        d["created_at_utc"] = iso(d["created_at"])
        d["links"] = {k: v for k, v in (("task", d["task_id"]), ("mission", d["mission_id"]),
                                        ("inbox", d["inbox_id"])) if v}
        return d

    def notification(self, nid):
        row = self.db.execute("SELECT * FROM notifications WHERE id=?", (nid,)).fetchone()
        return self._note(row) if row else None

    def notification_head(self):
        return self.db.execute("SELECT COALESCE(MAX(id),0) FROM notifications").fetchone()[0]

    def notifications(self, after=0, limit=100, unread=False):
        q, args = "SELECT * FROM notifications WHERE id>?", [int(after)]
        if unread:
            q += " AND read_at IS NULL"
        q += " ORDER BY id LIMIT ?"
        args.append(max(0, min(int(limit), 500)))
        return [self._note(r) for r in self.db.execute(q, args)] if args[-1] else []

    async def wait(self, after, timeout):
        """Until there is a notification after `after`, or timeout seconds pass (a long poll)."""
        if self._new is None:
            self._new = asyncio.Event()
        end = time.monotonic() + max(0.0, timeout)
        while self.notification_head() <= after:
            left = end - time.monotonic()
            if left <= 0:
                return False
            self._new.clear()
            try:
                await asyncio.wait_for(self._new.wait(), left)
            except asyncio.TimeoutError:
                return False
        return True

    def delivered(self, channel, through):
        """A channel confirms it has every notification up to `through` (never moves back)."""
        through = min(int(through), self.notification_head())
        self.db.execute("INSERT INTO deliveries(channel,through,updated_at,failures,last_error) VALUES(?,?,?,0,'') "
                        "ON CONFLICT(channel) DO UPDATE SET through=MAX(through, excluded.through), "
                        "updated_at=excluded.updated_at, failures=0, last_error=''", (channel, through, time.time()))
        return self.delivery(channel)

    def delivery_failed(self, channel, error):
        self.db.execute("INSERT INTO deliveries(channel,through,updated_at,failures,last_error) VALUES(?,0,?,1,?) "
                        "ON CONFLICT(channel) DO UPDATE SET failures=failures+1, last_error=excluded.last_error, "
                        "updated_at=excluded.updated_at", (channel, time.time(), str(error)[:300]))

    def delivery(self, channel):
        row = self.db.execute("SELECT * FROM deliveries WHERE channel=?", (channel,)).fetchone()
        through = row["through"] if row else 0
        pending = self.db.execute("SELECT COUNT(*) FROM notifications WHERE id>?", (through,)).fetchone()[0]
        return {"channel": channel, "through": through, "pending": pending,
                "updated_at_utc": iso(row["updated_at"]) if row else None,
                "failures": row["failures"] if row else 0, "last_error": row["last_error"] if row else ""}

    def deliveries(self):
        return [self.delivery(r[0]) for r in self.db.execute("SELECT channel FROM deliveries ORDER BY channel")]

    def mark_read(self, actor, ids=None, through=None):
        now = time.time()
        if ids:
            ids = [int(i) for i in ids][:500]
            cur = self.db.execute(f"UPDATE notifications SET read_at=?, read_by=? WHERE read_at IS NULL AND id IN "
                                  f"({','.join('?' * len(ids))})", (now, actor, *ids))
        elif through is not None:
            cur = self.db.execute("UPDATE notifications SET read_at=?, read_by=? WHERE read_at IS NULL AND id<=?",
                                  (now, actor, int(through)))
        else:
            raise ValueError("give ids or through")
        return {"marked": cur.rowcount, "unread": self.unread()}

    def unread(self):
        return self.db.execute("SELECT COUNT(*) FROM notifications WHERE read_at IS NULL").fetchone()[0]

    # ------------------------------------------------------------------ after a crash or restart
    def reconcile(self):
        """Record what a crash may have lost between a status write and its event. Only work that finished
        after the journal was installed counts, so an old database does not flood the inbox."""
        since = self.store.get("journal_since") or time.time()
        n = 0
        for t in self.db.execute("SELECT * FROM tasks WHERE finished_at>=? AND status IN ('done','failed','cancelled')",
                                 (since,)).fetchall():
            t = dict(t)
            for ev in E.task_events({**t, "status": "running"}, t, name=self.names.get(t["agent"])):
                n += bool(self.record(ev))
        for m in self.db.execute("SELECT * FROM missions WHERE finished_at>=? AND status IN "
                                 "('succeeded','failed','unverified','cancelled')", (since,)).fetchall():
            m = self.store.mission(m["id"], with_tasks=True)
            for ev in E.mission_events({**m, "status": "running"}, m):
                n += bool(self.record(ev))
        if n:
            log("warning", "reconciled events missing after a restart", count=n)
        return n
