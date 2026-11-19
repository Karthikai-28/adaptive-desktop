"""The morning standup and the evening summary: scheduled every day, kept, delivered to the phone.

Schedule (config.json "reports"): standup 10:00 and evening 19:00 in Asia/Kolkata, every calendar day.

Windows. Each report covers from the end of the previous report of its kind to its own scheduled time, so
consecutive reports neither leave a gap nor count anything twice (the first one covers the 24 hours before
its time). A catch-up report keeps that rule, so it covers the whole time the laptop was away.

Catch-up. The scheduler looks every 30 seconds. A report made more than GRACE_S after its time is a
catch-up and says so in its title and text ("scheduled 10:00, made 13:42"). Only the latest due time of each
kind is made; earlier ones that passed while the office was off are recorded as missed. Times before the
reports were installed (kv reports_since) are never made up afterwards.

Records (`reports` table, one row per kind and local date, so a restart can't make one twice): status
generated -> delivered (the phone confirmed the notification), missed, or failed (retried up to 3 times,
then an office.error inbox item). Each made report is also saved as Markdown in DATA/reports/.

The builders below are pure: data from office/tracker.py in, sections and Markdown out.
"""
import datetime as dt
import json
import time
from zoneinfo import ZoneInfo

from . import activity as A
from .config import DATA

KINDS = ("standup", "evening")
TITLES = {"standup": "Morning standup", "evening": "Evening summary"}
GRACE_S = 15 * 60
MAX_ATTEMPTS = 3
REPORTS = DATA / "reports"
DEFAULTS = {"enabled": True, "timezone": "Asia/Kolkata", "standup": "10:00", "evening": "19:00"}


# ------------------------------------------------------------------ the schedule (pure)
def settings(cfg):
    s = dict(DEFAULTS, **(cfg.get("reports") or {}))
    ZoneInfo(s["timezone"])
    for k in KINDS:
        h, m = (int(x) for x in s[k].split(":"))
        assert 0 <= h < 24 and 0 <= m < 60, f"reports.{k} must be HH:MM"
    return s


def slot_at(kind, day, s):
    """The scheduled moment (epoch) of `kind` on local date `day`."""
    h, m = (int(x) for x in s[kind].split(":"))
    return dt.datetime(day.year, day.month, day.day, h, m, tzinfo=ZoneInfo(s["timezone"])).timestamp()


def latest_slot(kind, now, s):
    """(local date, epoch) of the last scheduled time of `kind` at or before now."""
    day = dt.datetime.fromtimestamp(now, ZoneInfo(s["timezone"])).date()
    at = slot_at(kind, day, s)
    if at > now:
        day -= dt.timedelta(days=1)
        at = slot_at(kind, day, s)
    return day, at


def next_slot(kind, now, s):
    day, at = latest_slot(kind, now, s)
    day += dt.timedelta(days=1)
    return day, slot_at(kind, day, s)


def local(ts, s, fmt="%H:%M"):
    return dt.datetime.fromtimestamp(ts, ZoneInfo(s["timezone"])).strftime(fmt)


# ------------------------------------------------------------------ the reports (pure)
def _name(d, aid):
    return (d["agents"].get(aid) or {}).get("name") or aid or "-"


def _t(t):
    return f"#{t['id']} {t.get('title') or ''}".strip()


def priorities(d):
    """What to do first, from the records only: approvals, then failures and blocks, then quota and limits,
    then missions to check, then queued work in the order it will run."""
    out = []
    items = d["open_items"]
    for i in items:
        if i["kind"] == "approval":
            out.append({"level": "Critical", "text": f"Decide approval request #{i['id']}: {i['text']}",
                        "ref": f"inbox:{i['id']}"})
    for i in items:
        if i["kind"] in ("failed", "blocked"):
            out.append({"level": "High", "text": f"{i['title']}: run it again or cancel it (inbox #{i['id']})",
                        "ref": f"inbox:{i['id']}"})
    for i in items:
        if i["kind"] in ("quota", "limit", "error"):
            out.append({"level": "High", "text": f"{i['title']}: {i['text']}", "ref": f"inbox:{i['id']}"})
    for i in items:
        if i["kind"] in ("mission-failed", "mission-unverified"):
            out.append({"level": "Normal", "text": f"Check mission #{i['mission_id']}: {i['title']}",
                        "ref": f"mission:{i['mission_id']}"})
    status = d["task_status"]
    for t in d["queued"][:10]:
        wait = t.get("depends_on")
        note = f" (waits for #{wait}, {status.get(wait, 'unknown')})" if wait and status.get(wait) != "done" else ""
        out.append({"level": "Normal", "text": f"{_name(d, t['agent'])}: {_t(t)}{note}", "ref": f"task:{t['id']}"})
    return out


def _per_agent(d):
    by = {aid: {"agent": aid, "name": a["name"], "role": a["role"], "completed": [], "failed": [], "current": None,
                "next": [], "blockers": [], "active_s": 0.0, "idle_s": 0.0, "queue_s": 0.0, "tasks_time": {}}
          for aid, a in d["agents"].items()}
    for t in d["finished"]:
        row = by.get(t["agent"])
        if row:
            (row["completed"] if t["status"] == "done" else row["failed"]).append(t)
    for t in d["running"]:
        if t["agent"] in by:
            by[t["agent"]]["current"] = t
    for t in d["queued"]:
        if t["agent"] in by:
            by[t["agent"]]["next"].append(t)
    for i in d["open_items"]:
        if i.get("agent") in by:
            by[i["agent"]]["blockers"].append(i)
    for s in d["summary"]["agents"]:
        if s["agent"] in by:
            by[s["agent"]].update(active_s=s["active_s"], idle_s=s["idle_s"], queue_s=s["queue_s"],
                                  tasks_time=s["tasks"])
    for row in by.values():
        hot = any(i["priority"] in ("high", "critical") for i in row["blockers"])
        row["priority"] = "High" if hot else "Normal" if (row["current"] or row["next"]) else "Idle"
    return by


def _window_line(d, s):
    return f"{local(d['since'], s, '%a %d %b %H:%M')} – {local(d['until'], s, '%a %d %b %H:%M')} ({s['timezone']})"


def standup(d, s, made_at, scheduled_at, catch_up):
    agents = _per_agent(d)
    done = [t for t in d["finished"] if t["status"] == "done"]
    failed = [t for t in d["finished"] if t["status"] == "failed"]
    blockers = [i for i in d["open_items"] if i["kind"] in ("failed", "blocked", "quota", "limit", "error")]
    decisions = [i for i in d["open_items"] if i["kind"] in ("approval", "mission-unverified", "mission-failed")]
    waiting = [t for t in d["queued"] if t.get("depends_on") and d["task_status"].get(t["depends_on"]) != "done"]
    plan = priorities(d)
    title = f"{TITLES['standup']} — {local(scheduled_at, s)}"
    if catch_up:
        title += f" (catch-up, made {local(made_at, s, '%a %H:%M')})"
    summary = (f"{len(done)} finished, {len(failed)} failed since the last standup; {len(d['running'])} working now, "
               f"{len(d['queued'])} queued; {len(blockers)} blocker(s), {len(decisions)} decision(s) waiting.")
    L = [f"# {title}", "", f"*{_window_line(d, s)}*", ""]
    if catch_up:
        L += [f"> Catch-up: this standup was due at {local(scheduled_at, s, '%a %d %b %H:%M')} while the office was "
              f"not running, and was made at {local(made_at, s, '%a %d %b %H:%M')}. It covers the whole time since "
              "the previous one.", ""]
    L += ["## Team summary", "", summary, ""]
    L += ["## Completed (by agent)", ""] + ([f"- **{_name(d, t['agent'])}**: {_t(t)}" for t in done] or ["- Nothing finished."]) + [""]
    L += ["## In progress now", ""] + ([f"- **{_name(d, t['agent'])}**: {_t(t)}" + (f" (mission #{t['mission_id']})" if t.get("mission_id") else "")
                                         for t in d["running"]] or ["- Nobody is working on a task right now."]) + [""]
    L += ["## Today: planned, in priority order", ""] + ([f"{n}. **{p['level']}** — {p['text']}" for n, p in enumerate(plan, 1)]
                                                          or ["Nothing is queued."]) + [""]
    L += ["## Blockers", ""] + ([f"- {i['title']}: {i['text']} (inbox #{i['id']}, {i['state'].lower().replace('_', ' ')})" for i in blockers]
                                or ["- None."]) + [""]
    L += ["## Failed tasks that need attention", ""] + ([f"- **{_name(d, t['agent'])}**: {_t(t)} — {t['error'] or 'failed'}" for t in failed]
                                                         or ["- None."]) + [""]
    L += ["## Decisions waiting for you", ""] + ([f"- {i['title']}: {i['text']} (inbox #{i['id']})" for i in decisions] or ["- None."]) + [""]
    L += ["## Deadlines and dependencies", "",
          "- The office records no deadlines."] + [f"- {_t(t)} waits for #{t['depends_on']} ({d['task_status'].get(t['depends_on'], 'not found')})"
                                                     for t in waiting] + [""]
    L += ["## By agent", ""]
    for row in agents.values():
        L += [f"**{row['name']}** — {row['role']}",
              f"- Yesterday: " + ("; ".join(_t(t) for t in row["completed"]) or "nothing finished")
              + (f"; failed: {'; '.join(_t(t) for t in row['failed'])}" if row["failed"] else ""),
              f"- Today: " + ("; ".join(_t(t) for t in row["next"][:3]) or "nothing queued"),
              f"- Current task: " + (_t(row["current"]) if row["current"] else "none"),
              f"- Blockers: " + ("; ".join(i["title"] for i in row["blockers"]) or "none"),
              f"- Priority: {row['priority']}", ""]
    data = {"summary": summary, "completed": done, "failed": failed, "running": d["running"], "plan": plan,
            "blockers": blockers, "decisions": decisions, "dependencies": waiting, "agents": list(agents.values()),
            "deadlines": None}
    return title, summary, data, "\n".join(L).rstrip() + "\n"


def evening(d, s, made_at, scheduled_at, catch_up):
    agents = _per_agent(d)
    hist = d["history"]
    done = [t for t in d["finished"] if t["status"] == "done"]
    failed = [t for t in d["finished"] if t["status"] == "failed"]
    cancelled = [t for t in d["finished"] if t["status"] == "cancelled"]
    blocked = [i for i in d["open_items"] if i["kind"] == "blocked"]
    active = [a for a in agents.values() if a["active_s"] > 0 or a["completed"] or a["failed"]]
    total_active = sum(a["active_s"] for a in agents.values())
    est = d["summary"].get("estimated")
    tok = d["tokens"]
    title = f"{TITLES['evening']} — {local(scheduled_at, s)}"
    if catch_up:
        title += f" (catch-up, made {local(made_at, s, '%a %H:%M')})"
    summary = (f"{len(done)} completed, {len(d['running'])} in progress, {len(failed)} failed, {len(blocked)} blocked; "
               f"{len(active)} agent(s) active for {A.fmt_duration(total_active)} of work in total.")
    L = [f"# {title}", "", f"*{_window_line(d, s)}*", ""]
    if catch_up:
        L += [f"> Catch-up: due at {local(scheduled_at, s, '%a %d %b %H:%M')}, made at "
              f"{local(made_at, s, '%a %d %b %H:%M')} after the office was not running. It covers the whole time since "
              "the previous evening summary.", ""]
    if est:
        L += ["> Some times are estimated: that work finished before the activity journal existed, so only its last "
              "attempt's start and end are known.", ""]
    L += ["## Summary", "", summary, ""]
    L += ["## Completed", ""] + ([f"- **{_name(d, t['agent'])}**: {_t(t)}" for t in done] or ["- Nothing was completed."]) + [""]
    L += ["## Still in progress (not finished)", ""] + ([f"- **{_name(d, t['agent'])}**: {_t(t)}" for t in d["running"]] or ["- None."]) + [""]
    L += ["## Failed", ""] + ([f"- **{_name(d, t['agent'])}**: {_t(t)} — {t['error'] or 'failed'}" for t in failed] or ["- None."]) + [""]
    L += ["## Blocked", ""] + ([f"- {i['title']}: {i['text']}" for i in blocked] or ["- None."]) + [""]
    if cancelled:
        L += ["## Cancelled", ""] + [f"- {_t(t)}" for t in cancelled] + [""]
    L += ["## Execution time", "", "| Agent | Active | Idle | Queue wait (their tasks) | Runs |", "|---|---|---|---|---|"]
    for a in agents.values():
        L.append(f"| {a['name']} | {A.fmt_duration(a['active_s'])} | {A.fmt_duration(a['idle_s'])} | "
                 f"{A.fmt_duration(a['queue_s'])} | {sum(1 for h in hist if h['agent'] == a['agent'] and h['runs'])} |")
    L += ["", f"Waiting for approvals: {A.fmt_duration(d['summary']['approval_wait_s'])} over "
              f"{d['summary']['approvals']} request(s).", ""]
    if hist:
        L += ["### By task", "", "| Task | Agent | Ran | Queued | Outcome |", "|---|---|---|---|---|"]
        for h in hist[:40]:
            L.append(f"| {_t(h['task'])} | {_name(d, h['agent'])} | {A.fmt_duration(h['run_s'])}"
                     f"{' (est.)' if h['estimated'] else ''} | {A.fmt_duration(h['queue_s'])} | {h['outcome']} |")
        L.append("")
    L += ["## Missions", ""] + ([f"- #{m['id']} {m['title']}: **{m['status']}**, {m['passed']}/{m['criteria']} criteria passed"
                                 + (f" — {m['error'][:200]}" if m.get("error") and m["status"] != "succeeded" else "")
                                 for m in d["missions"]] or ["- No mission was active."]) + [""]
    L += ["## Outputs and evidence", ""]
    for t in done[:20]:
        first = next((ln.strip() for ln in (t.get("result") or "").splitlines() if ln.strip()), "")
        L.append(f"- {_t(t)}: {first[:200]}" if first else f"- {_t(t)}: (no report text)")
    if d["files"]:
        L += ["", "Files written in the workspace:"] + [f"- `{f['path']}`" for f in d["files"][:20]]
    if not done and not d["files"]:
        L.append("- None.")
    L += [""]
    L += ["## Retries and recovery", ""]
    L += [f"- {e['text']}" for e in d["retries"][:20]] or ["- No automatic retries."]
    L += [f"- Recovered: {r['title']}" for r in d["recovered"]]
    L += [""]
    L += ["## Tokens and cost", ""]
    if tok.get("available"):
        L += [f"- {_name(d, aid)}: {r['total']:,} tokens ({r['fresh']:,} fresh, {r['cached']:,} re-read, {r['out']:,} out)"
              for aid, r in sorted(tok["agents"].items(), key=lambda kv: -kv[1]["total"])] or ["- No model calls."]
        L.append(f"- Total: {tok['total']:,} tokens. Cost: not billed per token (Gemini and Claude run on the "
                 "subscriptions, local models on this laptop).")
    else:
        L.append("- Token usage is not available.")
    L += ["", "## Remaining work", ""] + ([f"- {_name(d, t['agent'])}: {_t(t)}" for t in d["queued"][:20]] or ["- Nothing queued."])
    L += ["", "## Unresolved blockers", ""] + ([f"- {i['title']} (inbox #{i['id']})" for i in d["open_items"]] or ["- None."])
    L += ["", "## Recommended priorities for tomorrow", ""] + ([f"{n}. **{p['level']}** — {p['text']}" for n, p in enumerate(priorities(d), 1)]
                                                            or ["Nothing is waiting."])
    data = {"summary": summary, "completed": done, "in_progress": d["running"], "failed": failed, "blocked": blocked,
            "cancelled": cancelled, "agents": list(agents.values()), "history": hist[:200], "missions": d["missions"],
            "files": d["files"], "retries": d["retries"], "recovered": d["recovered"], "tokens": tok,
            "remaining": d["queued"], "open_items": d["open_items"], "priorities": priorities(d),
            "approval_wait_s": d["summary"]["approval_wait_s"], "estimated": est}
    return title, summary, data, "\n".join(L).rstrip() + "\n"


BUILD = {"standup": standup, "evening": evening}


# ------------------------------------------------------------------ the scheduler
class Reports:
    def __init__(self, office):
        self.o = office
        self.db = office.store.db
        self.s = settings(office.cfg)

    def _row(self, r, full=False):
        if not r:
            return None
        d = dict(r)
        data, md = d.pop("data"), d.pop("markdown")
        if full:
            d["data"], d["markdown"] = json.loads(data or "{}"), md
        for k in ("scheduled_at", "window_start", "window_end", "generated_at", "delivered_at"):
            d[k + "_local"] = local(d[k], self.s, "%Y-%m-%d %H:%M") if d.get(k) else None
        d["timezone"] = self.s["timezone"]
        return d

    def get(self, rid, full=True):
        return self._row(self.db.execute("SELECT * FROM reports WHERE id=?", (rid,)).fetchone(), full)

    def list(self, kind=None, since=None, until=None, limit=50, status=None):
        q, args = "SELECT * FROM reports WHERE 1=1", []
        for col, val in (("kind", kind), ("status", status)):
            if val:
                q += f" AND {col}=?"; args.append(val)
        if since:
            q += " AND window_end>?"; args.append(float(since))
        if until:
            q += " AND window_start<?"; args.append(float(until))
        q += " ORDER BY COALESCE(scheduled_at, generated_at) DESC, id DESC LIMIT ?"
        args.append(max(1, min(int(limit), 500)))
        return [self._row(r) for r in self.db.execute(q, args)]

    def schedule(self, now=None):
        now = now or time.time()
        out = {"enabled": self.s["enabled"], "timezone": self.s["timezone"], "kinds": {}}
        for k in KINDS:
            _, nxt = next_slot(k, now, self.s)
            _, last = latest_slot(k, now, self.s)
            out["kinds"][k] = {"time": self.s[k], "next_at": nxt, "next_local": local(nxt, self.s, "%a %d %b %H:%M"),
                               "last_due_at": last, "last": (self.list(kind=k, limit=1) or [None])[0]}
        return out

    def _previous(self, kind, before):
        return self.db.execute("SELECT * FROM reports WHERE kind=? AND manual=0 AND status IN ('generated','delivered') "
                               "AND scheduled_at<? ORDER BY scheduled_at DESC LIMIT 1", (kind, before)).fetchone()

    def tick(self, now=None):
        """Make what is due, record what was missed, and note what the phone has received. Idempotent."""
        now = now or time.time()
        if not self.s["enabled"]:
            return []
        since = self.o.store.get("reports_since") or now
        made = []
        for kind in KINDS:
            day, at = latest_slot(kind, now, self.s)
            if at < since:
                continue
            row = self.db.execute("SELECT * FROM reports WHERE kind=? AND slot=?", (kind, day.isoformat())).fetchone()
            if row and (row["status"] != "failed" or row["attempts"] >= MAX_ATTEMPTS):
                continue
            prev = self._previous(kind, at)
            self._record_missed(kind, prev, day, since)
            start = prev["window_end"] if prev else at - 86400
            made.append(self.generate(kind, start, at, scheduled_at=at, slot=day.isoformat(),
                                      catch_up=now - at > GRACE_S, now=now))
        self._mark_delivered()
        return made

    def _record_missed(self, kind, prev, day, since):
        """Times between the previous report and this one that passed while the office was off."""
        d = day - dt.timedelta(days=1)
        stop = dt.date.fromisoformat(prev["slot"]) if prev else None
        while (stop is None or d > stop) and slot_at(kind, d, self.s) >= since:
            at = slot_at(kind, d, self.s)
            self.db.execute("INSERT OR IGNORE INTO reports(kind,slot,scheduled_at,window_start,window_end,status,"
                            "title,summary) VALUES(?,?,?,?,?,'missed',?,?)",
                            (kind, d.isoformat(), at, at, at, f"{TITLES[kind]} — {self.s[kind]} (missed)",
                             "The office was not running at this time; the next report covers this period."))
            d -= dt.timedelta(days=1)

    def generate(self, kind, start, end, scheduled_at=None, slot=None, catch_up=False, manual=False, now=None):
        now = now or time.time()
        slot = slot or f"manual-{now:.3f}"
        try:
            d = self.o.tracker.period(start, end, now)
            title, summary, data, md = BUILD[kind](d, self.s, now, scheduled_at or now, catch_up)
            if manual:
                title = f"{TITLES[kind]} (on demand, {local(now, self.s, '%a %H:%M')})"
                md = md.replace(md.splitlines()[0], f"# {title}", 1)
        except Exception as e:
            self.db.execute("INSERT INTO reports(kind,slot,scheduled_at,window_start,window_end,status,attempts,error,"
                            "manual) VALUES(?,?,?,?,?,'failed',1,?,?) ON CONFLICT(kind,slot) DO UPDATE SET "
                            "attempts=attempts+1, error=excluded.error", (kind, slot, scheduled_at, start, end,
                                                                          str(e)[:500], int(manual)))
            row = self.db.execute("SELECT * FROM reports WHERE kind=? AND slot=?", (kind, slot)).fetchone()
            if row["attempts"] >= MAX_ATTEMPTS:
                self.o.journal.raise_issue("office.error", f"error:report-{kind}", f"The {TITLES[kind].lower()} for "
                                           f"{slot} could not be made: {e}")
            return self._row(row)
        path = REPORTS / f"{slot}-{kind}.md"
        with self.o.store.transaction():
            self.db.execute(
                "INSERT INTO reports(kind,slot,scheduled_at,window_start,window_end,status,catch_up,manual,generated_at,"
                "attempts,error,path,title,summary,data,markdown) VALUES(?,?,?,?,?,'generated',?,?,?,1,'',?,?,?,?,?) "
                "ON CONFLICT(kind,slot) DO UPDATE SET status='generated', catch_up=excluded.catch_up, "
                "generated_at=excluded.generated_at, attempts=attempts+1, error='', path=excluded.path, "
                "title=excluded.title, summary=excluded.summary, data=excluded.data, markdown=excluded.markdown, "
                "window_start=excluded.window_start, window_end=excluded.window_end",
                (kind, slot, scheduled_at, start, end, int(catch_up), int(manual), now, str(path), title, summary,
                 json.dumps(data, default=str), md))
            row = self.db.execute("SELECT * FROM reports WHERE kind=? AND slot=?", (kind, slot)).fetchone()
            if not manual:
                ev = self.o.journal.record({
                    "type": "report.ready", "severity": "info", "text": summary, "agent": "",
                    "dedup": f"report.ready:{kind}:{slot}", "evidence": [f"report:{row['id']}"],
                    "ref": f"report:{row['id']}", "title": title})
                note = ev and self.db.execute("SELECT id FROM notifications WHERE seq=?", (ev["seq"],)).fetchone()
                if note:
                    self.db.execute("UPDATE reports SET notification_id=? WHERE id=?", (note[0], row["id"]))
        try:
            REPORTS.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(md)
            tmp.replace(path)
        except OSError as e:
            print(json.dumps({"log": "reports", "level": "error", "msg": "could not save", "error": str(e)}), flush=True)
        print(json.dumps({"log": "reports", "level": "info", "msg": "made", "kind": kind, "slot": slot,
                          "catch_up": catch_up, "window": [start, end]}), flush=True)
        return self.get(row["id"], full=False)

    def _mark_delivered(self):
        """A report is delivered once a phone has confirmed its notification (deliveries "link:<device>")."""
        through = self.db.execute("SELECT COALESCE(MAX(through),0) FROM deliveries WHERE channel LIKE 'link%'").fetchone()[0]
        self.db.execute("UPDATE reports SET status='delivered', delivered_at=? WHERE status='generated' AND "
                        "notification_id IS NOT NULL AND notification_id<=?", (time.time(), through))
