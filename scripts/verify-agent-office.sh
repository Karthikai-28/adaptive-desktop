#!/usr/bin/env bash
# Checks for Agent Office that spend no Gemini or Claude quota.
#
#   scripts/verify-agent-office.sh          syntax, roster, and a throwaway server's API and guards
#   scripts/verify-agent-office.sh --quick  syntax and roster only (no packages needed)
#
# The throwaway server runs on its own port with a temporary state folder, so the real office
# (and its data) is never touched.
set -Euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$REPO/services/agent-office"
QUICK=0; [ "${1:-}" = "--quick" ] && QUICK=1
TMP="$(mktemp -d)"; SERVER=""
# sandbox probes need a state folder outside /tmp: the sandbox mounts its own /tmp over anything in it
mkdir -p "${XDG_CACHE_HOME:-$HOME/.cache}"; SBX="$(mktemp -d -p "${XDG_CACHE_HOME:-$HOME/.cache}" office-verify.XXXXXX)"
cleanup() { [ -n "$SERVER" ] && kill "$SERVER" 2>/dev/null; rm -rf "$TMP" "$SBX"; }
trap cleanup EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

# 1. Python compiles, modules parse as ES modules, the roster is valid
python3 -m py_compile "$APP/server.py" "$APP"/office/*.py "$APP/bin/office" || fail "python syntax"
for f in "$APP"/static/*.js; do
    cp "$f" "$TMP/$(basename "$f" .js).mjs"
    node --check "$TMP/$(basename "$f" .js).mjs" || fail "js syntax: $f"
done
# Milestone 3: what the two views compute (views.js is pure): honest progress, timeline lanes, the figures
node --input-type=module -e "
import * as V from '$TMP/views.mjs';
const ok = (c, m) => { if (!c) { console.error('views.js: ' + m); process.exit(1); } };
ok(V.normalizeView('command') === 'command' && V.normalizeView('cockpit') === 'office' && V.normalizeView() === 'office', 'Virtual Office is the default');
ok(V.fmtDur(5) === '5s' && V.fmtDur(125) === '2m 05s' && V.fmtDur(3725) === '1h 02m', 'durations');
const p = V.missionProgress({ total_tasks: 4, done_tasks: 1, failed_tasks: 1 });
ok(p.text === '1 of 4 tasks done · 1 failed' && p.frac === 0.25, 'mission progress ' + JSON.stringify(p));
ok(V.missionProgress({ total_tasks: 0 }).frac === null, 'no bar without tasks');
const run = V.runProgress({ task: { id: 1, status: 'running' }, running_since: 100, actions: 3, queued_count: 2 }, 160);
ok(run === 'running 1m 00s · 3 actions · 2 queued' && !/%/.test(run), 'run progress is time and counts only: ' + run);
const L = V.lanes([{ agent: 'a', task: { id: 1 }, runs: [[50, 150, 'done'], [180, null, 'running']] }], 100, 200, ['a', 'b']);
const a = L.get('a');
ok(a.length === 2 && a[0].left === 0 && a[0].width === 50 && a[0].outcome === 'done' && a[1].left === 80 && a[1].width === 20 && L.get('b').length === 0, 'lanes ' + JSON.stringify(a));
ok(V.sortDesks([{ id: 'x', state: 'idle' }, { id: 'y', state: 'error' }, { id: 'z', state: 'working' }]).map(d => d.id).join() === 'z,y,x', 'urgency order');
const k = V.kpis({ counts: { agents: 8, active: 2, idle: 5, blocked: 1, error: 0, running_tasks: 2, queued_tasks: 3, done_today: 7, failed_today: 1, running_missions: 1 }, inbox: { NEEDS_ATTENTION: 2, critical: 1 } });
ok(k.length === 7 && k[0].value === '2/8' && k.find(x => x.key === 'decisions').value === 2 && k.find(x => x.key === 'failed').alert, 'figures');
ok(Object.keys(V.STATE_LABEL).sort().join() === 'blocked,error,idle,paused,working', 'the five status words');
" || fail "views.js rules"
python3 - "$APP/config.json" "$APP/static/map.js" <<'PY' || fail "config.json"
import json, re, sys
cfg = json.load(open(sys.argv[1]))
desks = set(re.findall(r"addDesk\('(\w+)'", open(sys.argv[2]).read()))
ids = [a["id"] for a in cfg["agents"]]
assert len(ids) == len(set(ids)), "duplicate agent ids"
assert cfg["manager"]["id"] not in ids, "manager id clashes with an agent"
for a in cfg["agents"]:
    for k in ("name", "role", "team", "desk", "voice", "look", "brief"):
        assert a.get(k), f"{a['id']}: missing {k}"
    assert a["desk"] in desks, f"{a['id']}: desk {a['desk']} is not on the map"
for st in cfg.get("studies", []):
    assert st["agent"] in ids, f"study {st['id']}: unknown agent {st['agent']}"
    assert st["repos"] and all(r.get("path") for r in st["repos"]), f"study {st['id']}: needs repos"
m = cfg["manager"]
allowed = {"claude-sonnet-5", "claude-sonnet-5-5", "claude-opus-5", "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6"}
for k in ("model", "complex_model"):
    assert m.get(k, "") in allowed | {""}, f"manager {k} {m.get(k)!r}: use Sonnet 5/5.5, or Opus 5 or below"
assert "sonnet" in (m.get("model") or "claude-sonnet-5-5"), "manager model must be Sonnet; Opus is only the complex_model"
provs = cfg.get("providers") or {"gemini": {"engine": "agy", "model": cfg.get("gemini_model")}}
for pid, pv in provs.items():
    assert pv.get("engine") in ("agy", "ollama", "claude") and pv.get("model"), f"provider {pid}: needs engine agy|ollama|claude and a model"
    assert "@" not in pid and pid != "claude", f"provider id {pid!r} is reserved or invalid"
assert any(pv["engine"] == "agy" for pv in provs.values()), "keep one agy (Gemini) provider"
for k in ("provider", "fallback"):
    assert not cfg.get(k) or cfg[k] in provs, f"{k} {cfg.get(k)!r} is not a provider"
for a in cfg["agents"]:
    assert not a.get("provider") or a["provider"] in provs, f"{a['id']}: unknown provider {a['provider']}"
used = [a["desk"] for a in cfg["agents"]]
assert len(used) == len(set(used)), "two agents share a desk"
print(f"roster ok: {len(ids)} agents + {cfg['manager']['name']}; providers: {', '.join(provs)}")
PY
PYTHONPATH="$APP" python3 - <<'PY' || fail "usage parser"
from office.quota import QuotaGuard, parse_usage

raw = """Gemini Models\tWeekly Limit Remaining\t17%\t2026-10-15T20:18:26Z
Gemini Models\tFive Hour Limit Remaining\tdisabled\t
Claude and GPT models\tWeekly Limit Remaining\t42%\t2026-10-15T19:15:52Z
Claude and GPT models\tFive Hour Limit Remaining\tdisabled\t
"""
rows = parse_usage(raw)
assert [(r["family"], r["window"], r["percent"]) for r in rows] == [
    ("gemini", "week", 17), ("gemini", "5h", None),
    ("claude", "week", 42), ("claude", "5h", None),
], rows
assert rows[1]["remaining"] == "disabled"
guard = object.__new__(QuotaGuard)
guard.usage = {"rows": [dict(rows[0], percent=0, remaining="0%"),
                         dict(rows[2], percent=0, remaining="0%", resets="2099-01-01T00:00:00Z")]}
assert guard.exhausted_until() == 1792095506.0, "only Gemini exhaustion may pause Gemini work"
PY
# An installed office may have the pre-mission task table. Migration must add the column before its index.
PYTHONPATH="$APP" python3 - "$TMP/old.db" <<'PY' || fail "old database migration"
import sqlite3, sys
p = sys.argv[1]
db = sqlite3.connect(p)
db.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, agent TEXT NOT NULL, title TEXT NOT NULL)")
db.commit(); db.close()
from office.store import Store
s = Store(p)
cols = {r[1] for r in s.db.execute("PRAGMA table_info(tasks)")}
assert "mission_id" in cols
assert any(r[1] == "tasks_mission" for r in s.db.execute("PRAGMA index_list(tasks)"))
PY
# ... and the first missions table, without risk, approval, verdicts or template
PYTHONPATH="$APP" python3 - "$TMP/old-missions.db" <<'PY' || fail "old missions table migration"
import sqlite3, sys
p = sys.argv[1]
db = sqlite3.connect(p)
db.execute("CREATE TABLE missions (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, objective TEXT NOT NULL, "
           "project TEXT DEFAULT '', repo TEXT DEFAULT '', criteria TEXT DEFAULT '[]', status TEXT NOT NULL DEFAULT 'queued', "
           "created_by TEXT DEFAULT 'operator', created_at REAL, started_at REAL, finished_at REAL, summary TEXT DEFAULT '', "
           "error TEXT DEFAULT '')")
db.execute("INSERT INTO missions(title, objective, criteria) VALUES('old', 'kept', '[\"c\"]')")
db.commit(); db.close()
from office.store import Store
s = Store(p)
m = s.mission(1)
assert m["objective"] == "kept" and m["verdicts"] == [] and m["template"] == {} and m["allowed_agents"] == [], m
assert s.update_mission(1, verdicts=[{"id": "C1"}])["verdicts"] == [{"id": "C1"}]
assert s.mission_count() == 1 and s.mission_ids() == {1}
PY
# mission verdicts: success needs PASS evidence for every criterion; the last report wins
PYTHONPATH="$APP" python3 - <<'PY' || fail "mission verdicts"
from office import verdicts as v
crit = ["builds", "tests pass", "documented"]
rows = v.judge(crit, ["C1: PASS - make ok\n- **C2**: FAIL: 2 tests fail\n| C3 | PASS | README updated |",
                      "C2 PASS — pytest: 40 passed"])
assert [r["verdict"] for r in rows] == ["PASS", "PASS", "PASS"], rows
assert rows[1]["evidence"] == "pytest: 40 passed", rows
assert v.outcome(rows) == ("succeeded", "")
assert v.outcome(v.judge(crit, ["C1: PASS - ok ok\nC2: FAIL - broken"]))[0] == "failed"
status, err = v.outcome(v.judge(crit, ["C1: PASS - fine\nC2: PASS\nC3: pass - yes it is"]))
assert status == "unverified" and "C2" in err and "C3" not in err, (status, err)     # PASS without evidence
assert v.outcome(v.judge(crit, ["All done, everything works!"]))[0] == "unverified"
assert v.parse("Cost: PASS - nope") == {} and v.parse("- [x] C1: PASS - yes")[1][0] == "PASS"
PY
# the server tells the manager's own `office` calls apart by process tree, not by what they claim
PYTHONPATH="$APP" python3 - <<'PY' || fail "caller identification"
import socket, subprocess, sys, time
from office import callers
srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(2)
port = srv.getsockname()[1]
code = f"import socket,time; s=socket.create_connection(('127.0.0.1',{port})); time.sleep(5)"
inner = subprocess.Popen([sys.executable, "-c", f"import subprocess,sys; subprocess.run([sys.executable,'-c',{code!r}])"])
other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
try:
    conn, (host, cport) = srv.accept()
    assert callers.owned_by([inner.pid], host, cport, port), "grandchild's connection not found in its tree"
    assert not callers.owned_by([other.pid], host, cport, port), "connection attributed to an unrelated process"
    assert not callers.owned_by([], host, cport, port)
finally:
    inner.kill(); other.kill()
PY
# Milestone 1: the event journal, Action Inbox and notifications (office/events.py, office/journal.py)
PYTHONPATH="$APP" python3 - "$TMP/journal.db" "$TMP/journal-old.db" <<'PY' || fail "event journal and Action Inbox"
import sqlite3, sys, time
from office import events as E
from office.journal import Journal
from office.store import Store

# --- pure rules
t0 = {"id": 7, "agent": "maya", "title": "Build", "status": "queued", "attempts": 0, "mission_id": None,
      "started_at": None, "finished_at": None, "error": ""}
run = {**t0, "status": "running", "attempts": 1, "started_at": 10.0}
assert [e["type"] for e in E.task_events(t0, run)] == ["task.started"]
assert [e["type"] for e in E.task_events(t0, {**run, "attempts": 2})] == ["task.resumed"]
assert [e["type"] for e in E.task_events(t0, run, resumed=True)] == ["task.resumed"]
fail_ = {**run, "status": "failed", "finished_at": 20.0, "error": "agy exited 1"}
assert E.task_events(run, fail_)[0]["type"] == "task.failed"
assert E.task_events(run, fail_)[0]["dedup"] == E.task_events(run, dict(fail_))[0]["dedup"]   # same fact, same key
assert E.task_events(run, {**fail_, "error": "blocked: task #3 failed"})[0]["type"] == "task.blocked"
assert E.task_events(run, {**run, "status": "queued", "error": "timeout"})[0]["type"] == "task.retry"
assert E.task_events(run, {**run, "status": "queued", "attempts": 0})[0]["type"] == "task.interrupted"
assert E.task_events(fail_, {**fail_, "status": "queued"})[0]["type"] == "task.requeued"
assert E.task_events(run, run) == []
assert E.issue_effect(E.task_events(run, fail_)[0]) == ("open", "task:7", "failed")
assert E.issue_effect(E.task_events(fail_, {**fail_, "status": "queued"})[0]) == ("progress", "task:7", None)
assert E.issue_effect(E.task_events(run, {**run, "status": "done", "finished_at": 30.0})[0]) == ("resolve", "task:7", None)
assert E.notification_for({"type": "task.failed"}) == ("high", None)
assert E.notification_for({"type": "approval.requested"}) == ("critical", None)
assert E.notification_for({"type": "task.completed"}) == ("normal", "office.done")
assert E.notification_for({"type": "task.started"}) is None
m_run = {"id": 3, "title": "M", "status": "running", "tasks": [], "finished_at": None}
m_fail = E.mission_events(m_run, {**m_run, "status": "failed", "finished_at": 5.0, "tasks": [{"status": "failed"}]})[0]
assert m_fail.get("quiet") and E.issue_effect(m_fail) is None and E.notification_for(m_fail) is None
m_verdict = E.mission_events(m_run, {**m_run, "status": "failed", "finished_at": 5.0, "tasks": [{"status": "done"}]})[0]
assert E.issue_effect(m_verdict) == ("open", "mission:3", "mission-failed")
for a, s, n in (("ack", E.NEEDS, E.WORKING), ("resolve", E.WORKING, E.RESOLVED), ("reopen", E.RESOLVED, E.NEEDS)):
    assert E.transition(s, a) == n
for a, s in (("ack", E.RESOLVED), ("reopen", E.NEEDS), ("resolve", E.RESOLVED)):
    try:
        E.transition(s, a); raise AssertionError(f"{a} from {s} allowed")
    except ValueError:
        pass
assert E.request_key("workflow-run", "w", {"a": 1, "b": 2}) == E.request_key("workflow-run", "w", {"b": 2, "a": 1})
red = E.redact("failed: api_key=abcd1234efgh token ghp_" + "a" * 30 + " key sk-ant-xyzxyzxyzxyz OPKEY12345678", ["OPKEY12345678"])
assert "abcd1234efgh" not in red and "ghp_" not in red and "sk-ant" not in red and "OPKEY" not in red, red

# --- the journal on a real database
p = sys.argv[1]
s = Store(p)
from office.store import MIGRATIONS
assert s.version() == MIGRATIONS[-1][0] == 2 and s.get("journal_since") and s.get("reports_since")
j = Journal(s, {"maya": "Maya"}, secrets=lambda: ("SECRETKEY123",))
t = s.add_task("maya", "Build it")
s.update_task(t["id"], status="running", started_at=time.time(), attempts=1)
s.update_task(t["id"], status="failed", finished_at=time.time(), error="it broke; key SECRETKEY123")
items = j.inbox()["items"]
assert len(items) == 1 and items[0]["state"] == E.NEEDS and items[0]["kind"] == "failed" and items[0]["priority"] == "high", items
assert "SECRETKEY123" not in items[0]["text"], items[0]["text"]
notes = j.notifications()
assert len(notes) == 1 and notes[0]["priority"] == "high" and notes[0]["links"]["task"] == t["id"], notes
types = [e["type"] for e in j.events()["events"]]
assert types == ["task.created", "task.started", "task.failed"], types
# the event history is append-only
for sql in ("UPDATE event_log SET text='x'", "DELETE FROM event_log"):
    try:
        s.db.execute(sql); raise AssertionError(sql + " was allowed")
    except sqlite3.DatabaseError:
        pass
# a restart: everything is still there, nothing is recorded twice, numbering continues
head = j.head()
s2 = Store(p); j2 = Journal(s2, {"maya": "Maya"})
assert j2.head() == head and j2.reconcile() == 0 and len(j2.inbox()["items"]) == 1 and len(j2.notifications()) == 1
item = j2.inbox()["items"][0]
# the blocker stays until it is really resolved
try:
    j2.act(item["id"], "resolve", "operator"); raise AssertionError("a live failure was resolved")
except PermissionError:
    pass
try:
    j2.act(item["id"], "dismiss", "phone"); raise AssertionError("a live failure was dismissed without the key")
except PermissionError:
    pass
assert j2.act(item["id"], "ack", "phone")["state"] == E.WORKING
assert j2.inbox(state=E.WORKING)["total"] == 1
s2.update_task(t["id"], status="queued", error="", finished_at=None)                   # the operator retries it
s2.update_task(t["id"], status="running", started_at=time.time(), attempts=2)
s2.update_task(t["id"], status="failed", finished_at=time.time() + 1, error="broke again")   # ... and it fails again
again = j2.inbox()["items"]
assert len(again) == 1 and again[0]["state"] == E.NEEDS and len(j2.notifications()) == 2, again   # one item, a new alert
s2.update_task(t["id"], status="queued", error="", finished_at=None)
s2.update_task(t["id"], status="running", started_at=time.time(), attempts=3)
s2.update_task(t["id"], status="done", finished_at=time.time() + 2, result="ok")
done = j2.item(item["id"])
assert done["state"] == E.RESOLVED and done["resolution"] == "recovered" and not done["live"], done
hist = [e["type"] for e in done["history"]]
assert hist.index("inbox.acknowledged") < hist.index("task.completed"), hist
assert j2.act(item["id"], "reopen", "operator")["state"] == E.NEEDS
assert j2.act(item["id"], "resolve", "operator")["state"] == E.RESOLVED          # nothing live: resolvable
# reconnecting clients get what they missed, in order
evs = j2.events(after=2)["events"]
assert [e["seq"] for e in evs] == sorted(e["seq"] for e in evs) and evs[0]["seq"] == 3 and evs[0]["ts_utc"].endswith("+00:00")
assert [n["id"] for n in j2.notifications(after=1)] == [2, 3]
assert j2.delivered("link", 2)["pending"] == 1 and j2.delivered("link", 1)["through"] == 2   # never moves back
assert j2.mark_read("operator", through=2)["unread"] == 1
# approvals: one request asked twice is one item and one alert; declining closes it
a1 = j2.request_approval("workflow-run", "move", {"inputs": {}}, "manager", "run move")
a2 = j2.request_approval("workflow-run", "move", {"inputs": {}}, "manager", "run move")
assert a1["id"] == a2["id"] and a1["priority"] == "critical"
assert sum(1 for n in j2.notifications(limit=500) if n["priority"] == "critical") == 1
assert j2.act(a1["id"], "ack", "phone")["state"] == E.WORKING        # acknowledging approves nothing ...
try:
    j2.act(a1["id"], "resolve", "phone"); raise AssertionError("an approval was resolved without approving it")
except ValueError:
    pass
assert j2.act(a1["id"], "decline", "operator")["resolution"] == "declined"
a3 = j2.request_approval("workflow-run", "move", {"inputs": {}}, "manager", "run move")   # asked again later
assert a3["id"] == a1["id"] and a3["state"] == E.NEEDS and a3["generation"] == 2
seqs = [e["seq"] for e in j2.events(limit=1000)["events"]]
assert seqs == list(range(1, len(seqs) + 1)), seqs                     # numbered without gaps, even after duplicates

# an office upgraded with old finished work does not turn its history into alerts
old = sys.argv[2]
db = sqlite3.connect(old)
db.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, agent TEXT NOT NULL, title TEXT NOT NULL, status TEXT, "
           "finished_at REAL, error TEXT DEFAULT '', attempts INTEGER DEFAULT 1)")
db.execute("INSERT INTO tasks(agent,title,status,finished_at,error) VALUES('maya','old','failed',?, 'x')", (time.time() - 99,))
db.commit(); db.close()
so = Store(old)
jo = Journal(so)
assert so.version() == 2 and jo.reconcile() == 0 and jo.inbox()["total"] == 0 and jo.notifications() == []
PY
# push channels (office/channels.py): WhatsApp is off and can't send; a failing channel keeps what it missed
# and gets it again, in order, after a backoff; a channel only ever carries a short line
PYTHONPATH="$APP" python3 - "$TMP/channels.db" "$APP/config.json" <<'PY' || fail "notification channels"
import asyncio, json, sys
from office import channels as C
from office.journal import Journal
from office.store import Store

cfg = json.load(open(sys.argv[2]))
wa = C.from_config(cfg)
assert [c.name for c in wa] == ["whatsapp"] and not wa[0].enabled, "WhatsApp must be off by default"
assert C.Dispatcher(None, wa).channels == []
assert C.concise({"title": "T", "text": "x " * 400}).endswith("…") and len(C.concise({"title": "T", "text": "x " * 400})) <= 280

s = Store(sys.argv[1]); j = Journal(s)
for i in range(3):
    j.raise_issue("office.error", f"error:{i}", f"problem {i}")
class Flaky(C.Channel):
    name = "flaky"
    def __init__(self):
        super().__init__({"enabled": True, "min_priority": "high"}); self.sent, self.down = [], True
    async def send(self, note):
        if self.down:
            raise ConnectionError("unreachable")
        assert set(note["message"]) and "\n" not in note["message"]
        self.sent.append(note["id"])
ch = Flaky(); d = C.Dispatcher(j, [ch])
async def main():
    await d.once()
    assert ch.sent == [] and j.delivery("push:flaky")["pending"] == 3 and j.delivery("push:flaky")["failures"] == 1
    ch.down = False
    await d.once()
    assert ch.sent == [], "retried before its backoff"
    d.retry_at["flaky"] = 0
    await d.once()
    assert ch.sent == [1, 2, 3] and j.delivery("push:flaky")["pending"] == 0, ch.sent
asyncio.run(main())
PY
# Milestone 2 rules: timelines from events (run, queue; overlaps counted once), the IST schedule, the reports
PYTHONPATH="$APP" python3 - <<'PY' || fail "activity timelines and report rules"
import datetime as dt
from office import activity as A, reports as R

ev = lambda seq, ts, typ, tid=1, agent="maya": {"seq": seq, "ts": ts, "type": typ, "task_id": tid, "agent": agent, "mission_id": None}
events = [ev(1, 0, "task.created"), ev(2, 10, "task.started"), ev(3, 40, "task.retry"), ev(4, 50, "task.resumed"),
          ev(5, 70, "task.interrupted"), ev(6, 100, "task.resumed"), ev(7, 130, "task.completed"),
          ev(8, 20, "task.created", 2), ev(9, 60, "task.started", 2)]
tl = A.task_timelines(events, now=200)
assert tl[1]["runs"] == [[10, 40, "retry"], [50, 70, "interrupted"], [100, 130, "done"]], tl[1]
assert tl[1]["queued"] == [[0, 10], [40, 50], [70, 100]] and not tl[1]["running"], tl[1]
assert tl[2]["runs"] == [[60, 200, "running"]] and tl[2]["running"]
assert A.union_seconds([[0, 10], [5, 20], [30, 40]]) == 30          # overlapping time counted once
assert A.clip([[0, 100, "x"]], 50, 80) == [[50, 80, "x"]]
s = A.agent_summary(tl, 0, 200, ["maya", "arjun"])
assert s["maya"]["active_s"] == 30 + 150 and s["arjun"]["active_s"] == 0 and s["arjun"]["idle_s"] == 200, s
assert s["maya"]["tasks"] == {1: 80.0, 2: 140.0}                    # each task's own time stays whole
est = A.estimated_timeline({"agent": "zoe", "started_at": 5, "finished_at": 9, "status": "done", "created_at": 1}, 50)
assert est["estimated"] and est["runs"] == [[5, 9, "done"]] and est["queued"] == [[1, 5]]
assert A.fmt_duration(59) == "59s" and A.fmt_duration(3720) == "1h 02m"

# the schedule: 10:00 and 19:00 in Asia/Kolkata (UTC+5:30), every day
S = R.settings({})
ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
at = lambda *a: dt.datetime(*a, tzinfo=ist).timestamp()
assert R.latest_slot("standup", at(2026, 11, 19, 10, 0), S) == (dt.date(2026, 11, 19), at(2026, 11, 19, 10, 0))
assert R.latest_slot("standup", at(2026, 11, 19, 9, 59), S) == (dt.date(2026, 11, 18), at(2026, 11, 18, 10, 0))
assert R.latest_slot("evening", at(2026, 11, 20, 2, 0), S) == (dt.date(2026, 11, 19), at(2026, 11, 19, 19, 0))
assert R.next_slot("evening", at(2026, 11, 19, 19, 0), S)[1] == at(2026, 11, 20, 19, 0)
assert R.slot_at("standup", dt.date(2026, 11, 21), S) == dt.datetime(2026, 11, 21, 4, 30, tzinfo=dt.timezone.utc).timestamp()

# the reports, from a period's data
t = lambda i, st, agent="maya", **k: dict({"id": i, "agent": agent, "title": f"Job {i}", "status": st, "mission_id": None,
                                           "depends_on": None, "result": "Done: wrote report.md", "error": ""}, **k)
d = {"since": at(2026, 11, 18, 19, 0), "until": at(2026, 11, 19, 19, 0), "now": at(2026, 11, 19, 19, 0),
     "agents": {"maya": {"name": "Maya", "role": "Engineer"}, "arjun": {"name": "Arjun", "role": "Research"}},
     "summary": {"agents": [{"agent": "maya", "active_s": 3600, "idle_s": 82800, "queue_s": 60, "tasks": {1: 3600}, "estimated": False},
                            {"agent": "arjun", "active_s": 0, "idle_s": 86400, "queue_s": 0, "tasks": {}, "estimated": False}],
                 "approval_wait_s": 0, "approvals": 0, "estimated": False},
     "history": [{"task": t(1, "done"), "agent": "maya", "mission_id": None, "runs": [[0, 3600, "done"]], "run_s": 3600,
                  "queue_s": 60, "estimated": False, "outcome": "done"}],
     "finished": [t(1, "done"), t(2, "failed", "arjun", error="agy exited 2")],
     "running": [t(3, "running")], "queued": [t(4, "queued", "arjun", depends_on=3)],
     "task_status": {1: "done", 2: "failed", 3: "running", 4: "queued"},
     "missions": [{"id": 5, "title": "Ship", "status": "succeeded", "criteria": 2, "passed": 2, "error": ""}],
     "retries": [], "recovered": [],
     "open_items": [{"id": 9, "kind": "failed", "title": "Arjun: task #2 failed", "text": "agy exited 2", "priority": "high",
                     "state": "NEEDS_ATTENTION", "agent": "arjun", "mission_id": None},
                    {"id": 10, "kind": "approval", "title": "Approval needed", "text": "run move", "priority": "critical",
                     "state": "NEEDS_ATTENTION", "agent": "", "mission_id": None}],
     "tokens": {"available": True, "agents": {"maya": {"total": 1000, "fresh": 100, "cached": 800, "out": 100, "calls": 3}}, "total": 1000},
     "files": [{"path": "projects/x/report.md", "modified": 0}], "assignments": None}
title, summary, data, md = R.standup(d, S, d["now"], at(2026, 11, 19, 10, 0), False)
assert title == "Morning standup — 10:00" and "Catch-up" not in md
assert [p["level"] for p in data["plan"]][:2] == ["Critical", "High"], data["plan"]      # approvals, then failures
assert "waits for #3, running" in md and "The office records no deadlines" in md
maya = next(a for a in data["agents"] if a["agent"] == "maya")
arjun = next(a for a in data["agents"] if a["agent"] == "arjun")
assert maya["priority"] == "Normal" and arjun["priority"] == "High" and "**Arjun** — Research" in md and "- Priority: High" in md
title, summary, data, md = R.evening(d, S, at(2026, 11, 20, 8, 0), at(2026, 11, 19, 19, 0), True)
assert "catch-up" in title and "> Catch-up: due at" in md, title
assert "## Still in progress (not finished)" in md and "#3 Job 3" in md.split("## Still in progress")[1].split("##")[0]
assert "#3 Job 3" not in md.split("## Completed")[1].split("##")[0]                  # in progress is never "completed"
assert "| Maya | 1h 00m |" in md and "not billed per token" in md and "projects/x/report.md" in md
assert "2/2 criteria passed" in md and data["priorities"][0]["level"] == "Critical"
# Milestone 3: the one status word every view shows
D = A.desk_state
assert D("working") == ("working", "Working") and D("thinking") == ("working", "Replying")
assert D("idle", True) == ("working", "In a meeting") and D("paused") == ("paused", "Paused")
assert D("quota") == ("blocked", "Waiting for quota") and D("idle") == ("idle", "Idle")
assert D("idle", items=[{"kind": "approval", "state": "NEEDS_ATTENTION"}]) == ("blocked", "Waiting for your decision")
assert D("idle", items=[{"kind": "blocked", "state": "IN_PROGRESS"}])[0] == "blocked"
assert D("idle", items=[{"kind": "failed", "state": "NEEDS_ATTENTION"}]) == ("error", "Last task failed")
assert D("idle", items=[{"kind": "failed", "state": "RESOLVED"}])[0] == "idle"
assert D("working", items=[{"kind": "failed", "state": "NEEDS_ATTENTION"}])[0] == "working"   # what it does now wins
assert set(A.DESK_STATES) == {"working", "idle", "blocked", "error", "paused"}
from office import events as EV
tree = EV.redact_tree({"a": ["token=supersecretvalue1", {"b": "ghp_" + "x" * 30}], "n": 3, "ok": "plain"})
assert tree == {"a": ["[redacted]", {"b": "[redacted]"}], "n": 3, "ok": "plain"}, tree
PY
[ "$QUICK" = 1 ] && { echo "quick checks passed"; exit 0; }

# 2. A throwaway server: API, guards, path traversal
PYTHONPATH="$REPO/.local/office-pydeps" python3 -c "import fastapi, uvicorn" 2>/dev/null ||
    { echo "skipped server checks: run scripts/install-agent-office.sh first"; exit 0; }
# mission state follows its tasks, and finished work is judged by the report's PASS/FAIL evidence
OFFICE_STATE="$TMP/lifecycle" OFFICE_NO_STUDY=1 OFFICE_NO_REPO_SCAN=1 PYTHONPATH="$REPO/.local/office-pydeps:$APP" python3 - "$APP" <<'PY' || fail "mission lifecycle"
import asyncio, json, sys
from office import config
from office.config import DATA
from office.core import Office
from office.store import Store

async def main():
    store = Store(DATA / "office.db")
    store.set("paused", True)                       # nothing may start a real agent
    o = Office(config.load(), store)
    agent = next(iter(o.agents))
    m = await o.add_mission(agent, "Check", "Do it", ["builds", "tested"])
    tid = m["tasks"][0]["id"]
    writes = []
    orig = store.update_mission
    store.update_mission = lambda mid, **kw: (writes.append(kw), orig(mid, **kw))[1]
    assert (await o._sync_mission(m["id"]))["status"] == "queued" and writes == [], writes   # nothing changed, nothing written
    async def finish(status, result="", error=""):
        store.update_task(tid, status=status, result=result, error=error)
        return await o._sync_mission(m["id"])
    r = await finish("done", "Report\nC1: PASS - make: ok\nC2: PASS - pytest 12 passed")
    assert r["status"] == "succeeded" and r["error"] == "" and [v["verdict"] for v in r["verdicts"]] == ["PASS", "PASS"], r
    r = await finish("done", "C1: PASS - make ok\nC2: FAIL - 3 tests fail")
    assert r["status"] == "failed" and "C2" in r["error"], r
    r = await finish("done", "Everything is great.")
    assert r["status"] == "unverified" and "C1" in r["error"], r
    r = await finish("failed", error="agent crashed")
    assert r["status"] == "failed" and "agent crashed" in r["error"] and r["verdicts"] == [], r
    await o.retry_task(tid)                          # reopening clears the old outcome
    r = store.mission(m["id"])
    assert r["status"] == "queued" and r["error"] == "" and r["summary"] == "" and r["finished_at"] is None, r
    store.update_task(tid, status="running")         # the server stopped mid-task ...
    await o._sync_mission(m["id"])
    assert store.mission(m["id"])["status"] == "running"
    o2 = Office(config.load(), store)               # ... and restarts: the mission is re-derived at once
    o2.manager.start = o2.study.start = o2.quota.start = o2.graphs.start = o2.ledger.start = lambda: None
    o2._chat_worker = lambda aid: asyncio.sleep(0)
    o2._provider_loop = lambda: asyncio.sleep(0)
    await o2.start()
    assert store.mission(m["id"])["status"] == "queued", store.mission(m["id"])
    for bad in ({"risk": "read", "repo": "/nonexistent"}, {"risk": "hardware"}, {"allowed_agents": ["nobody"]}):
        try:
            await o.add_mission(agent, "x", "y", ["z"], repo=bad.pop("repo", ""), **bad)
        except ValueError:
            continue
        raise AssertionError(f"mission accepted {bad}")

asyncio.run(main())
PY
# pausing the office stops a running task, holds replies and manager jobs, survives a restart, and the
# resume continues the task's own conversation (fake runs: no agent is started)
OFFICE_STATE="$TMP/pause" OFFICE_NO_STUDY=1 OFFICE_NO_REPO_SCAN=1 PYTHONPATH="$REPO/.local/office-pydeps:$APP" python3 - "$APP" <<'PY' || fail "office pause and resume"
import asyncio
from office import agy, config
from office.config import DATA
from office.core import Office
from office.store import Store

runs = []
class FakeRun:
    def __init__(self, prompt, conv):
        self.prompt, self.conv, self.done, self.result = prompt, conv, asyncio.Event(), agy.AgyResult()
        runs.append(self)
    async def wait(self):
        await self.done.wait()
        return self.result
    def cancel(self):
        self.result.cancelled, self.result.conv_id, self.result.steps, self.result.tokens = True, "conv-1", 3, 100
        self.done.set()
    def finish(self, text):
        self.result.status, self.result.text, self.result.conv_id, self.result.steps = "SUCCESS", text, "conv-1", 2
        self.done.set()

def office(store):
    o = Office(config.load(), store)
    o.provider_paused = lambda pid, tools=True: False
    def run(aid, pid, prompt, conv, *a, **k):
        r = FakeRun(prompt, conv); r.provider = pid; return r
    o._run = run
    o.study.start = o.quota.start = o.graphs.start = o.ledger.start = lambda: None
    o._provider_loop = lambda: asyncio.sleep(0)
    async def turn(prompt, kind): return "manager reply", ""
    o.manager._turn = turn
    return o

async def settle(cond):
    for _ in range(100):
        if cond():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("timed out")

async def main():
    store = Store(DATA / "office.db")
    o = office(store)
    await o.start()
    agent = next(iter(o.agents))
    t = await o.add_task(agent, "Long job", "do it")
    await settle(lambda: runs and store.task(t["id"])["status"] == "running")
    await o.update_settings(paused=True)
    await settle(lambda: store.task(t["id"])["status"] == "queued")
    row = store.task(t["id"])
    assert row["attempts"] == 0 and row["steps"] == 3, row
    assert store.get(f"resume:{t['id']}")["conv"] == "conv-1"
    assert o.agent_state(agent)["status"] == "paused" and o.settings()["paused_at"]
    o.kick(); await asyncio.sleep(0.1)
    assert len(runs) == 1 and store.task(t["id"])["status"] == "queued", "a task started while paused"
    await o.dm(agent, "are you there?")
    await settle(lambda: store.get("held_chats", {}).get(agent))
    o.manager.chat("plan the week")
    await settle(lambda: store.get("mgr_held"))
    assert not store.messages("manager"), "the manager answered while paused"

    o2 = office(store)                              # the machine restarts while paused
    o2._chat_worker = lambda aid: asyncio.sleep(0)
    await o2.start()
    assert o2.settings()["paused"] and o2.manager.pending == 1 and store.get("held_chats", {}).get(agent)
    o2.kick(); await asyncio.sleep(0.1)
    assert len(runs) == 1, "a task started after a restart while paused"
    await o2.update_settings(paused=False)
    await settle(lambda: len(runs) == 2)
    assert runs[1].conv == "conv-1" and "has now resumed" in runs[1].prompt, (runs[1].conv, runs[1].prompt)
    assert o2.chat_q[agent].qsize() == 1 and not store.get("held_chats")
    await settle(lambda: any(m["text"] == "manager reply" for m in store.messages("manager")))
    assert not store.get("mgr_held")
    runs[1].finish("C1 done")
    await settle(lambda: store.task(t["id"])["status"] == "done")
    row = store.task(t["id"])
    assert row["steps"] == 5 and row["attempts"] == 1 and not store.get(f"resume:{t['id']}"), row
    t2 = await o2.add_task(agent, "Interrupted by a shutdown", "do it")
    await settle(lambda: len(runs) == 3 and store.task(t2["id"])["status"] == "running")
    await o2.shutdown()                             # not paused: the task still continues after the restart
    assert store.task(t2["id"])["status"] == "queued" and store.get(f"resume:{t2['id']}")["conv"] == "conv-1"

    # a hard stop (killed before the shutdown could queue it again): the run it finds at start was interrupted,
    # not tried, so the task keeps its one automatic retry
    store.delete(f"resume:{t2['id']}"); store.update_task(t2["id"], status="running", attempts=1)
    # Claude plans by itself: only a turn that assigned work gets the coverage pass
    o3 = office(store)
    await o3.start()
    await settle(lambda: store.task(t2["id"])["status"] == "running" and len(runs) == 4)
    assert store.task(t2["id"])["attempts"] == 1, store.task(t2["id"])
    assert "interrupted part-way" in runs[3].prompt, runs[3].prompt      # ... and continues from its partial work
    prompts = []
    async def answers(prompt, kind):
        prompts.append(prompt)
        return "an answer", ""
    o3.manager._turn = answers
    o3.manager.chat("how is it going?")
    await settle(lambda: prompts and any(m["text"] == "an answer" for m in store.messages("manager")))
    await asyncio.sleep(0.05)
    assert len(prompts) == 1, "a turn that assigned nothing got a coverage pass"
    async def assigns(prompt, kind):
        prompts.append(prompt)
        if len(prompts) == 2:
            await o3.add_task(agent, "One job", "do it", "", "manager")
        return "dispatched", ""
    o3.manager._turn = assigns
    o3.manager.chat("build it")
    await settle(lambda: len(prompts) == 3)
    assert prompts[2].startswith("[office coverage check]"), prompts[2]
    assert all(a in prompts[2] for a in o3.agents if a != agent), prompts[2]
    await o3.shutdown()

asyncio.run(main())
PY
# Milestone 1 through the real scheduler (fake runs): a failing task in a mission gives one inbox item and one
# alert, survives a restart, and is resolved only when the work really succeeds
OFFICE_STATE="$TMP/journal-office" OFFICE_NO_STUDY=1 OFFICE_NO_REPO_SCAN=1 PYTHONPATH="$REPO/.local/office-pydeps:$APP" python3 - "$APP" <<'PY' || fail "inbox through the office"
import asyncio
from office import agy, config
from office.config import DATA
from office.core import Office
from office.store import Store

runs = []
class FakeRun:
    def __init__(self):
        self.done, self.result = asyncio.Event(), agy.AgyResult()
        runs.append(self)
    async def wait(self):
        await self.done.wait(); return self.result
    def cancel(self):
        self.result.cancelled = True; self.done.set()
    def fail(self, err):
        self.result.error = err; self.done.set()
    def finish(self, text):
        self.result.status, self.result.text = "SUCCESS", text; self.done.set()

def office(store):
    o = Office(config.load(), store)
    o.provider_paused = lambda pid, tools=True: False
    def run(*a, **k):
        r = FakeRun(); r.provider = a[1]; return r
    o._run = run
    o.manager.start = o.study.start = o.quota.start = o.graphs.start = o.ledger.start = lambda: None
    o._provider_loop = lambda: asyncio.sleep(0)
    o._chat_worker = lambda aid: asyncio.sleep(0)
    sent = []
    o.broadcast = lambda msg: (sent.append(msg), asyncio.sleep(0))[1]
    o.sent = sent
    return o

async def settle(cond):
    for _ in range(200):
        if cond():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("timed out")

async def main():
    store = Store(DATA / "office.db")
    o = office(store)
    await o.start()
    agent = next(iter(o.agents))
    m = await o.add_mission(agent, "Ship", "Ship it", ["works"])
    tid = m["tasks"][0]["id"]
    await settle(lambda: len(runs) == 1)
    runs[0].fail("agy exited 2")                                   # first failure: retried by itself
    await settle(lambda: len(runs) == 2)
    runs[1].fail("agy exited 2 again")                             # second: the task fails
    await settle(lambda: store.task(tid)["status"] == "failed")
    await settle(lambda: store.mission(m["id"])["status"] == "failed")
    j = o.journal
    items = j.inbox()["items"]
    assert len(items) == 1 and items[0]["issue"] == f"task:{tid}" and items[0]["mission_id"] == m["id"], items
    assert [n["priority"] for n in j.notifications()] == ["high"], j.notifications()
    types = [e["type"] for e in j.events(limit=1000)["events"]]
    for want in ("mission.created", "task.created", "task.started", "task.retry", "task.resumed", "task.failed",
                 "mission.failed"):
        assert want in types, (want, types)
    assert any(msg.get("type") == "notification" for msg in o.sent) and any(msg.get("type") == "inbox" for msg in o.sent)
    assert o.snapshot()["inbox"]["NEEDS_ATTENTION"] == 1 and o.snapshot()["journal_head"] == j.head()
    await o.shutdown()

    o2 = office(store)                                             # restart: the blocker is still there
    await o2.start()
    j2 = o2.journal
    assert j2.inbox(state="NEEDS_ATTENTION")["total"] == 1 and len(j2.notifications()) == 1
    await o2.retry_task(tid)                                       # recovery: in progress, not resolved
    assert j2.item_by_issue(f"task:{tid}")["state"] == "IN_PROGRESS"
    await settle(lambda: len(runs) == 3)
    runs[2].finish("Done.\nC1: PASS - it works")
    await settle(lambda: store.mission(m["id"])["status"] == "succeeded")
    item = j2.item_by_issue(f"task:{tid}")
    assert item["state"] == "RESOLVED" and item["resolution"] == "recovered", item
    assert [n["title"] for n in j2.notifications()][-1].startswith("Mission #"), j2.notifications()
    await o2.shutdown()

asyncio.run(main())
PY
# Milestone 2 through the office (fake runs): measured work time, current assignments, and the scheduled reports:
# once per time even across restarts, catch-up labelled with the missed times recorded, windows without gaps
OFFICE_STATE="$TMP/reports-office" OFFICE_NO_STUDY=1 OFFICE_NO_REPO_SCAN=1 PYTHONPATH="$REPO/.local/office-pydeps:$APP" python3 - "$APP" <<'PY' || fail "activity and scheduled reports"
import asyncio, datetime as dt, time
from office import agy, config, reports as R
from office.config import DATA
from office.core import Office
from office.store import Store

runs = []
class FakeRun:
    def __init__(self):
        self.done, self.result = asyncio.Event(), agy.AgyResult(); runs.append(self)
    async def wait(self):
        await self.done.wait(); return self.result
    def cancel(self):
        self.result.cancelled = True; self.done.set()
    def finish(self, text):
        self.result.status, self.result.text = "SUCCESS", text; self.done.set()
    def fail(self, err):
        self.result.error = err; self.done.set()

def office(store):
    o = Office(config.load(), store)
    o.provider_paused = lambda pid, tools=True: False
    def run(*a, **k):
        r = FakeRun(); r.provider = a[1]; return r
    o._run = run
    o.manager.start = o.study.start = o.quota.start = o.graphs.start = o.ledger.start = lambda: None
    o._provider_loop = o._journal_loop = lambda: asyncio.sleep(0)
    o._chat_worker = lambda aid: asyncio.sleep(0)
    return o

async def settle(cond):
    for _ in range(200):
        if cond():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("timed out")

async def main():
    store = Store(DATA / "office.db")
    o = office(store)
    await o.start()
    agent = next(iter(o.agents))
    t = await o.add_task(agent, "Measured job", "do it")
    await settle(lambda: len(runs) == 1)
    now_agents = {a["id"]: a for a in o.tracker.assignments()}
    assert set(now_agents) == set(o.agents)
    me = now_agents[agent]
    assert me["status"] == "working" and me["task"]["id"] == t["id"] and me["running_since"], me
    # Milestone 3: one overview for every view; the status word, honest progress (counts, never a percentage)
    store.add_event(agent, "run", "$ curl -H 'Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123' x", t["id"])
    leak = [a for a in o.tracker.overview()["agents"] if "abcdefghijklmnop" in str(a)]
    assert not leak, "a credential reached the overview: " + str(leak)
    store.add_event(agent, "write", "Wrote notes.md", t["id"])
    ov = o.tracker.overview()
    me3 = next(a for a in ov["agents"] if a["id"] == agent)
    doing = o.tracker.board()["columns"]["doing"]
    assert [c["id"] for c in doing] == [t["id"]] and doing[0]["actions"] == 2 and doing[0]["last"] == "Wrote notes.md", doing
    assert me3["state"] == "working" and me3["state_label"] == "Working" and me3["actions"] == 2, me3
    assert me3["recent"][0]["text"] == "Wrote notes.md" and "percent" not in str(me3).lower()
    assert ov["counts"]["active"] == 1 and ov["counts"]["running_tasks"] == 1 and ov["counts"]["agents"] == len(o.agents)
    assert ov["timezone"] == "Asia/Kolkata" and ov["day_start"] <= time.time() and set(ov["inbox"]) >= {"NEEDS_ATTENTION"}
    await asyncio.sleep(0.4)
    runs[0].finish("Done.")
    await settle(lambda: store.task(t["id"])["status"] == "done")
    ov = o.tracker.overview()
    assert ov["counts"]["done_today"] >= 1 and ov["counts"]["active"] == 0
    assert next(a for a in ov["agents"] if a["id"] == agent)["state"] == "idle"
    # a failure leaves the desk at "error" until it is dealt with; the inbox item is the same one everywhere
    f = await o.add_task(agent, "Doomed job", "do it")
    await settle(lambda: len(runs) == 2); runs[1].fail("agy exited 2")
    await settle(lambda: len(runs) == 3); runs[2].fail("agy exited 2 again")
    await settle(lambda: store.task(f["id"])["status"] == "failed")
    ov = o.tracker.overview()
    desk = next(a for a in ov["agents"] if a["id"] == agent)
    assert desk["state"] == "error" and desk["blockers"][0]["kind"] == "failed", desk
    assert ov["counts"]["error"] == 1 and ov["counts"]["failed_today"] == 1 and ov["inbox"]["NEEDS_ATTENTION"] >= 1
    b = o.tracker.board()
    cols = b["columns"]
    assert [n["task"]["id"] for n in cols["needs_you"]] == [f["id"]] and cols["needs_you"][0]["kind"] == "failed", cols["needs_you"]
    assert {c["id"] for c in cols["done"]} >= {t["id"], f["id"]} and not cols["todo"] and not cols["doing"], cols
    assert next(c for c in cols["done"] if c["id"] == t["id"])["run_s"] > 0.35 and len(b["agents"]) == len(o.agents)
    o.journal.act(desk["blockers"][0]["id"], "dismiss", "operator", "seen", True)
    assert next(a for a in o.tracker.overview()["agents"] if a["id"] == agent)["state"] == "idle"
    timing = o.tracker.task_timing(t["id"])
    assert 0.35 < timing["run_s"] < 2 and timing["runs"][0][2] == "done" and not timing["estimated"], timing
    summ = {r["agent"]: r for r in o.tracker.summary(time.time() - 60, time.time())["agents"]}
    assert 0.35 < summ[agent]["active_s"] < 2 and summ[agent]["tasks"][t["id"]] == timing["run_s"], summ[agent]
    hist = o.tracker.history(time.time() - 60, time.time())
    assert [h["task"]["id"] for h in hist] == [f["id"], t["id"]] and hist[1]["outcome"] == "done", hist
    assert hist[0]["outcome"] == "failed"

    # the schedule, with the clock moved: installed on 18 Nov 2026 at 09:00 IST
    S = o.reports.s
    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    at = lambda *a: dt.datetime(*a, tzinfo=ist).timestamp()
    store.set("reports_since", at(2026, 11, 18, 9, 0))
    assert o.reports.tick(at(2026, 11, 18, 9, 30)) == []                               # nothing due yet
    made = o.reports.tick(at(2026, 11, 18, 10, 0, 30))
    assert [r["kind"] for r in made] == ["standup"] and not made[0]["catch_up"] and made[0]["status"] == "generated", made
    assert made[0]["window_end"] == at(2026, 11, 18, 10, 0) and made[0]["window_start"] == at(2026, 11, 17, 10, 0)
    assert o.reports.tick(at(2026, 11, 18, 10, 5)) == []                               # once per time
    o2 = office(store)                                                                  # ... even after a restart
    assert o2.reports.tick(at(2026, 11, 18, 10, 6)) == []
    ev = o2.reports.tick(at(2026, 11, 18, 19, 1))
    assert [r["kind"] for r in ev] == ["evening"] and ev[0]["window_start"] == at(2026, 11, 17, 19, 0)
    full = o2.reports.get(ev[0]["id"])
    assert full["markdown"].startswith("# Evening summary — 19:00") and "Measured job" not in full["markdown"]   # another day
    real = o2.reports.get(o2.reports.generate("evening", time.time() - 120, time.time() + 1, manual=True)["id"])
    assert "Measured job" in real["markdown"].split("## Completed")[1].split("##")[0], real["markdown"]
    assert any(h["task"]["id"] == t["id"] and h["run_s"] > 0.35 for h in real["data"]["history"])
    note = [n for n in o2.journal.notifications(limit=500) if n.get("report_id") == ev[0]["id"]]
    assert len(note) == 1 and note[0]["group"] == "office.reports" and full["notification_id"] == note[0]["id"]
    assert (DATA / "reports" / "2026-11-18-evening.md").read_text() == full["markdown"]
    # the laptop is off for two days: one catch-up per kind, the missed times recorded, no gap in the windows
    made = o2.reports.tick(at(2026, 11, 21, 8, 0))
    assert [(r["kind"], r["catch_up"]) for r in made] == [("standup", 1), ("evening", 1)], made
    sup = next(r for r in made if r["kind"] == "standup")
    assert sup["window_start"] == at(2026, 11, 18, 10, 0) and sup["window_end"] == at(2026, 11, 20, 10, 0)
    assert "catch-up" in sup["title"] and "Catch-up" in o2.reports.get(sup["id"])["markdown"]
    missed = sorted((r["kind"], r["slot"]) for r in o2.reports.list(status="missed"))
    assert missed == [("evening", "2026-11-19"), ("standup", "2026-11-19")], missed
    # delivered once a phone confirms its notification
    o2.journal.delivered("link:phone1", o2.journal.notification_head())
    o2.reports.tick(at(2026, 11, 21, 8, 1))
    assert {r["status"] for r in o2.reports.list() if not r["manual"] and r["status"] != "missed"} == {"delivered"}
    # a report that can't be made is retried, then raised in the inbox; it never claims to exist
    o2.tracker.period = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full"))
    for minute in (1, 2, 3, 4):
        o2.reports.tick(at(2026, 11, 21, 10, minute))
    bad = o2.reports.list(kind="standup", limit=1)[0]
    assert bad["status"] == "failed" and bad["attempts"] == 3 and "disk full" in bad["error"], bad
    assert o2.journal.item_by_issue("error:report-standup")["state"] == "NEEDS_ATTENTION"
    await o.shutdown()

asyncio.run(main())
PY
PORT=8799
OFFICE_STATE="$TMP/state" OFFICE_PORT=$PORT OFFICE_NO_STUDY=1 OFFICE_NO_REPO_SCAN=1 OFFICE_LINK_PID_FILE="$TMP/link.pid" \
    PYTHONPATH="$REPO/.local/office-pydeps" \
    python3 "$APP/server.py" >"$TMP/server.log" 2>&1 &
SERVER=$!
for _ in $(seq 1 40); do curl -fsS -o /dev/null "http://127.0.0.1:$PORT/api/state" 2>/dev/null && break; sleep 0.25; done
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
B="http://127.0.0.1:$PORT"
[ "$(code "$B/api/state")" = 200 ] || { cat "$TMP/server.log"; fail "server did not start"; }
[ "$(curl -fsS "$B/api/health" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(str(d["ok"] and d["local_only"]).lower())')" = true ] || fail "health endpoint"
[ "$(code "$B/")" = 200 ] || fail "page"
[ "$(code "$B/static/app.js")" = 200 ] || fail "static files"
[ "$(code -X POST -H 'Content-Type: application/json' -d '{}' "$B/api/settings")" = 403 ] || fail "POST without X-Office header was accepted"
[ "$(code -X POST -H 'X-Office: 1' -H 'Origin: http://evil.example' -H 'Content-Type: application/json' -d '{}' "$B/api/settings")" = 403 ] || fail "cross-site POST was accepted"
[ "$(code -H 'Host: evil.example' "$B/api/state")" = 403 ] || fail "foreign Host header was accepted"
[ "$(code "$B/api/files?path=../../..")" = 403 ] || fail "path traversal out of the workspace"
[ "$(code -X POST -H 'X-Office: 1' -H 'Content-Type: application/json' -d '{"agent":"nobody","title":"x"}' "$B/api/tasks")" = 400 ] || fail "task for an unknown agent was accepted"
# pausing is the owner's: an agent's command (same loopback, no key) can't stop the office
[ "$(code -X POST -H 'X-Office: 1' -H 'Content-Type: application/json' -d '{"paused":true}' "$B/api/settings")" = 403 ] || fail "paused without the operator key"
[ "$(code -X POST -H 'X-Office: 1' -H "X-Office-Operator: $(cat "$TMP/state/data/operator.key")" -H 'Content-Type: application/json' -d '{"autopilot":false,"paused":true}' "$B/api/settings")" = 200 ] || fail "settings"
curl -fsS "$B/api/state" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert len(d["roster"]) >= 2 and d["settings"]["autopilot"] is False and isinstance(d["missions"], list)' || fail "state"
# Mission Control records live in the office's private data, never in the agents' workspace
REC="$TMP/state/data/mission-control"
KEY="$(cat "$TMP/state/data/operator.key")"; [ -n "$KEY" ] || fail "operator key was not created"
[ "$(stat -c %a "$TMP/state/data/operator.key")" = 600 ] || fail "operator key is readable by others"
OP=(-H "X-Office-Operator: $KEY")
J=(-H 'X-Office: 1' -H 'Content-Type: application/json')
post() { curl -fsS -X POST "${J[@]}" "$@"; }
# missions are outcome contracts: objective + measurable criteria + a scoped first task
[ "$(code -X POST "${J[@]}" -d '{"agent":"maya","title":"Prove it","objective":"Produce a checked result","criteria":[]}' "$B/api/missions")" = 400 ] || fail "mission without criteria was accepted"
MID="$(post -d '{"agent":"maya","title":"Prove it","objective":"Produce a checked result","criteria":["The result passes its check"]}' "$B/api/missions" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["status"] == "queued" and d["tasks"][0]["mission_id"] == d["id"] and d["criteria"] == ["The result passes its check"] and d["risk"] == "read" and d["created_by"] == "operator", d; print(d["id"])')" || fail "create mission"
curl -fsS "$B/api/missions/$MID" | python3 -c 'import json,sys; d=json.load(sys.stdin); b=d["tasks"][0]["body"]; assert len(d["tasks"]) == 1 and "- C1: The result passes its check" in b and "C1: PASS - " in b' || fail "mission detail"
# the manager's own missions count against its hourly task limit and are attributed to it
post -H 'X-Office-Actor: manager' -d '{"agent":"maya","title":"Managed","objective":"o","criteria":["c"]}' "$B/api/missions" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["created_by"] == "manager" and d["tasks"][0]["created_by"] == "manager", d' || fail "manager mission attribution"
[ "$(code -X POST "${J[@]}" -d "{\"agent\":\"maya\",\"title\":\"x\",\"mission_id\":$MID,\"repo\":\"$TMP\"}" "$B/api/tasks")" = 400 ] || fail "task widened its mission's repository"
[ "$(code -X POST "${J[@]}" -H 'X-Office: 1' "$B/api/missions/$MID/cancel")" = 200 ] || fail "cancel mission"
curl -fsS "$B/api/missions/$MID" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["status"] == "cancelled" and d["tasks"][0]["status"] == "cancelled"' || fail "mission cancellation state"
[ "$(code -X POST "${J[@]}" -d "{\"agent\":\"maya\",\"title\":\"late\",\"mission_id\":$MID}" "$B/api/tasks")" = 400 ] || fail "task added to a finished mission"
CID="$(post -d "{\"mission_id\":$MID,\"command\":\"pytest -q\",\"parameters\":{\"seed\":\"42\"},\"datasets\":[\"bag://test\"],\"results\":[\"report.md\"]}" "$B/api/capsules" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["schema"] == 1 and d["command"] == "pytest -q" and d["parameters"]["seed"] == "42"; print(d["id"])')" || fail "create work capsule"
curl -fsS "$B/api/capsules/$CID" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["mission_id"] and d["path"] == sys.argv[1] + "/capsules/" + d["id"] + ".json", d["path"]' "$REC" || fail "read work capsule"
[ ! -e "$TMP/state/company/capsules" ] && [ ! -e "$TMP/state/company/workflows" ] && [ ! -e "$TMP/state/company/exports" ] || fail "Mission Control records in the agents' workspace"
[ "$(code "$B/api/capsules/../../office.db")" = 404 ] || fail "capsule path traversal"
echo '{"id":"broken"}' > "$REC/capsules/20000101-000000-deadbeef.json"; echo 'not json' > "$REC/capsules/20000101-000000-0badf00d.json"
curl -fsS "$B/api/evidence/search?q=checked%20result&mission_id=$MID" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["mission_id"] and "truncated" in d and any(r["kind"] == "mission" and r["ref"].startswith("mission:") for r in d["results"])' || fail "mission evidence search"
curl -fsS "$B/api/evidence/search?q=pytest" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert any(r["kind"] == "capsule" for r in d["results"])' || fail "evidence search with an unreadable capsule"
rm -f "$REC/capsules/20000101-000000-deadbeef.json" "$REC/capsules/20000101-000000-0badf00d.json"
[ "$(code "$B/api/evidence/search?q=test&mission_id=99999")" = 400 ] || fail "evidence search accepted an unknown mission"
RMID="$(post -d '{"agent":"maya","problem":"the test robot loses localization","bag":"bag://localization-test"}' "$B/api/missions/ros-investigation" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert len(d["criteria"]) == 5 and "ROS setup snapshot" in d["objective"] and d["template"]["kind"] == "ros-investigation" and not d.get("capsule_error"); print(d["id"])')" || fail "ROS investigation mission"
curl -fsS "$B/api/capsules?mission_id=$RMID" | python3 -c "import json,sys; assert [c for c in json.load(sys.stdin) if c['mission_id'] == $RMID]" || fail "ROS investigation capsule"
[ "$(code -X POST "${J[@]}" -d '{"agent":"maya","problem":"p","baseline_bag":"/nonexistent"}' "$B/api/missions/ros-investigation")" = 400 ] || fail "baseline without a recording was accepted"
# rosbag comparisons are deterministic and become part of the mission evidence capsule
mkdir -p "$TMP/baseline-bag" "$TMP/candidate-bag" "$TMP/loose" "$TMP/not-a-bag"
cat > "$TMP/baseline-bag/metadata.yaml" <<'JSON'
{"rosbag2_bagfile_information":{"duration":{"nanoseconds":1000000000},"message_count":110,"topics_with_message_count":[{"topic_metadata":{"name":"/scan","type":"sensor_msgs/msg/LaserScan"},"message_count":100},{"topic_metadata":{"name":"/tf","type":"tf2_msgs/msg/TFMessage"},"message_count":10}]}}
JSON
cat > "$TMP/candidate-bag/metadata.yaml" <<'JSON'
{"rosbag2_bagfile_information":{"duration":{"nanoseconds":900000000},"message_count":35,"topics_with_message_count":[{"topic_metadata":{"name":"/scan","type":"sensor_msgs/msg/LaserScan"},"message_count":25},{"topic_metadata":{"name":"/odom","type":"nav_msgs/msg/Odometry"},"message_count":10}]}}
JSON
: > "$TMP/candidate-bag/candidate_0.mcap"; : > "$TMP/loose/run.mcap"
echo '[1, 2, 3]' > "$TMP/not-a-bag/metadata.yaml"
post -d "{\"baseline\":\"$TMP/baseline-bag\",\"candidate\":\"$TMP/candidate-bag\"}" "$B/api/ros/compare" | \
    python3 -c 'import json,sys; d=json.load(sys.stdin); assert not d["ok"] and d["message_delta"] == -75 and any("/tf" in x for x in d["flags"])' || fail "ROS bag comparison"
post -d "{\"baseline\":\"$TMP/baseline-bag/metadata.yaml\",\"candidate\":\"$TMP/candidate-bag/candidate_0.mcap\"}" "$B/api/ros/compare" | \
    python3 -c 'import json,sys; assert json.load(sys.stdin)["message_delta"] == -75' || fail "ROS comparison of a file inside a bag folder"
[ "$(code -X POST "${J[@]}" -d "{\"baseline\":\"$TMP/baseline-bag\",\"candidate\":\"$TMP/loose/run.mcap\"}" "$B/api/ros/compare")" = 400 ] || fail "lone MCAP without metadata"
[ "$(code -X POST "${J[@]}" -d "{\"baseline\":\"$TMP/baseline-bag\",\"candidate\":\"$TMP/not-a-bag\"}" "$B/api/ros/compare")" = 400 ] || fail "malformed rosbag metadata is not a 400"
CMID="$(post -d "{\"agent\":\"maya\",\"problem\":\"planner stalls in replay\",\"baseline_bag\":\"$TMP/baseline-bag\",\"bag\":\"$TMP/candidate-bag/candidate_0.mcap\",\"simulation_command\":\"ros2 launch demo replay.launch.py\"}" \
    "$B/api/missions/ros-investigation" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert "Recording comparison" in d["objective"] and "Simulation or replay command" in d["objective"]; print(d["id"])')" || fail "compared ROS investigation mission"
curl -fsS "$B/api/capsules?mission_id=$CMID" | python3 -c "import json,sys; assert json.load(sys.stdin)" || fail "compared ROS capsule"
# reusable workflows preserve role and repository boundaries; higher-risk runs need the operator
git init -q "$TMP/repo-a" && git init -q "$TMP/repo-b" || fail "test repositories"
[ "$(code -X POST "${J[@]}" -d '{"id":"bad-read","title":"Bad","objective":"Read","criteria":["done"],"risk":"read","repo":"/tmp/writable"}' "$B/api/workflows")" = 400 ] || fail "read workflow accepted writable repo"
[ "$(code -X POST "${J[@]}" -d '{"id":"bad-role","title":"Bad","objective":"Read","criteria":["done"],"risk":"read","allowed_agents":["maya","nobody"]}' "$B/api/workflows")" = 400 ] || fail "workflow accepted an unknown role"
[ "$(code -X POST "${J[@]}" -d '{"id":"bad-owner","title":"Bad","objective":"Read","criteria":["done"],"agent":"zoe","risk":"read","allowed_agents":["maya"]}' "$B/api/workflows")" = 400 ] || fail "workflow owner outside its allowed agents"
python3 -c 'import json; print(json.dumps({"id":"bad-many","title":"Bad","objective":"o","criteria":["c%d" % i for i in range(21)]}))' | \
    { [ "$(code -X POST "${J[@]}" -d @- "$B/api/workflows")" = 400 ]; } || fail "workflow silently dropped criteria"
python3 -c 'import json; print(json.dumps({"id":"bad-long","title":"Bad","objective":"o","criteria":["x" * 501]}))' | \
    { [ "$(code -X POST "${J[@]}" -d @- "$B/api/workflows")" = 400 ]; } || fail "workflow accepted a criterion no mission can take"
post -d '{"id":"inspect-component","title":"Inspect {{component}}","objective":"Explain {{component}} with evidence","criteria":["A cited {{component}} report exists"],"agent":"maya","risk":"read","allowed_agents":["maya"]}' \
    "$B/api/workflows" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["id"] == "inspect-component" and d["allowed_agents"] == ["maya"] and d["created_by"] == "operator"' || fail "save workflow"
[ -f "$REC/workflows/inspect-component.json" ] || fail "workflow is not in the private records"
[ "$(code -X POST "${J[@]}" -d '{"id":"inspect-component","title":"Hijacked","objective":"o","criteria":["c"],"risk":"read"}' "$B/api/workflows")" = 400 ] || fail "workflow overwritten without the operator key"
[ "$(code -X POST "${J[@]}" -H 'X-Office-Operator: wrong' -d '{"id":"inspect-component","title":"Hijacked","objective":"o","criteria":["c"],"risk":"read"}' "$B/api/workflows")" = 400 ] || fail "workflow overwritten with a wrong key"
WMID="$(post -d '{"inputs":{"component":"planner"},"agent":"maya"}' "$B/api/workflows/inspect-component/run" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["title"] == "Inspect planner" and "planner" in d["criteria"][0] and d["workflow_id"] == "inspect-component" and d["allowed_agents"] == ["maya"]; print(d["id"])')" || fail "run workflow"
[ "$(code -X POST "${J[@]}" -d '{"inputs":{"component":"planner"},"agent":"zoe"}' "$B/api/workflows/inspect-component/run")" = 400 ] || fail "workflow role boundary"
[ "$(code -X POST "${J[@]}" -d "{\"agent\":\"zoe\",\"title\":\"x\",\"mission_id\":$WMID}" "$B/api/tasks")" = 400 ] || fail "task outside the mission's allowed agents"
post -d '{"id":"zoe-only","title":"Zoe only","objective":"o","criteria":["c"],"risk":"read","allowed_agents":["zoe"]}' "$B/api/workflows" >/dev/null || fail "save role-limited workflow"
post -d '{}' "$B/api/workflows/zoe-only/run" | python3 -c 'import json,sys; assert json.load(sys.stdin)["tasks"][0]["agent"] == "zoe"' || fail "workflow without an owner did not use its allowed agent"
post -d '{"id":"no-repo","title":"No repo","objective":"o","criteria":["c"],"risk":"write"}' "$B/api/workflows" >/dev/null || fail "save workflow without a repository"
[ "$(code -X POST "${J[@]}" -d "{\"repo\":\"$TMP/repo-a\"}" "$B/api/workflows/no-repo/run")" = 400 ] || fail "run widened a workflow without a repository"
post -d "{\"id\":\"repo-a\",\"title\":\"Repo A\",\"objective\":\"o\",\"criteria\":[\"c\"],\"repo\":\"$TMP/repo-a/\"}" "$B/api/workflows" | python3 -c 'import json,sys; assert json.load(sys.stdin)["repo"] == sys.argv[1]' "$TMP/repo-a" || fail "workflow repository is not resolved"
post -d "{\"repo\":\"$TMP/repo-a/\"}" "$B/api/workflows/repo-a/run" | python3 -c 'import json,sys; assert json.load(sys.stdin)["repo"] == sys.argv[1]' "$TMP/repo-a" || fail "workflow run with the same repository"
[ "$(code -X POST "${J[@]}" -d "{\"repo\":\"$TMP/repo-b\"}" "$B/api/workflows/repo-a/run")" = 400 ] || fail "workflow run switched repository"
post -d '{"id":"move-robot","title":"Move robot","objective":"Run movement check","criteria":["Robot stops safely"],"agent":"maya","risk":"hardware"}' "$B/api/workflows" >/dev/null || fail "save hardware workflow"
[ "$(code -X POST "${J[@]}" -d '{}' "$B/api/workflows/move-robot/run")" = 400 ] || fail "hardware workflow ran without approval"
[ "$(code -X POST "${J[@]}" -d '{"approved":true}' "$B/api/workflows/move-robot/run")" = 403 ] || fail "hardware workflow approved without the operator key"
[ "$(code -X POST "${J[@]}" -H 'X-Office-Operator: wrong' -d '{"approved":true}' "$B/api/workflows/move-robot/run")" = 403 ] || fail "hardware workflow approved with a wrong key"
[ "$(code -X POST "${J[@]}" "${OP[@]}" -d '{"id":"move-robot","title":"Move robot","objective":"Run movement check","criteria":["Robot stops safely"],"agent":"maya","risk":"write"}' "$B/api/workflows")" = 200 ] || fail "operator could not change a workflow"
post "${OP[@]}" -d '{"id":"move-robot","title":"Move robot","objective":"Run movement check","criteria":["Robot stops safely"],"agent":"maya","risk":"hardware"}' "$B/api/workflows" >/dev/null || fail "operator restore of the hardware workflow"
HMID="$(post "${OP[@]}" -d '{"approved":true}' "$B/api/workflows/move-robot/run" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["risk"] == "hardware" and d["approved_by"] == "operator" and d["approved_at"] and d["workflow_id"] == "move-robot"; print(d["id"])')" || fail "approved hardware workflow"
HTID="$(curl -fsS "$B/api/missions/$HMID" | python3 -c 'import json,sys; print(json.load(sys.stdin)["tasks"][0]["id"])')"
[ "$(code -X POST "${J[@]}" -d "{\"agent\":\"maya\",\"title\":\"more\",\"mission_id\":$HMID}" "$B/api/tasks")" = 403 ] || fail "work added to an approved hardware mission without the key"
code -X POST "${J[@]}" "$B/api/tasks/$HTID/cancel" >/dev/null
[ "$(code -X POST "${J[@]}" "$B/api/tasks/$HTID/retry")" = 403 ] || fail "hardware mission task re-run without the key"
[ "$(code -X POST "${J[@]}" "${OP[@]}" "$B/api/tasks/$HTID/retry")" = 200 ] || fail "operator re-run of a hardware mission task"
code -X POST "${J[@]}" "$B/api/missions/$HMID/cancel" >/dev/null
# Action Inbox over HTTP: a refused hardware run waits for approval; acknowledging it starts nothing, and only the
# operator key approves it, through the same checks as a fresh run
MISSIONS() { curl -fsS "$B/api/missions?limit=500" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))'; }
[ "$(code -X POST "${J[@]}" -H 'X-Office-Actor: manager' -d '{"agent":"maya"}' "$B/api/workflows/move-robot/run")" = 400 ] || fail "hardware workflow ran without approval (inbox)"
AID="$(curl -fsS "$B/api/inbox?kind=approval&state=NEEDS_ATTENTION" | python3 -c 'import json,sys; d=json.load(sys.stdin); it=[i for i in d["items"] if i["has_request"] and i["text"].startswith("manager asks")]; assert len(it) == 1 and it[0]["priority"] == "critical", d; print(it[0]["id"])')" || fail "approval request in the inbox"
BEFORE="$(MISSIONS)"
# the Action Inbox is the owner's: a keyless local caller (an agent's command, say) and a forged phone header are
# refused; the paired phone is recognised by Adaptive Link's process (here a stand-in that writes its pid)
[ "$(code -X POST "${J[@]}" -d '{}' "$B/api/inbox/$AID/ack")" = 403 ] || fail "a keyless caller acted on the inbox"
[ "$(code -X POST "${J[@]}" -H 'X-Office-Actor: phone' -d '{}' "$B/api/inbox/$AID/decline")" = 403 ] || fail "a forged phone header declined an approval"
as_phone() {   # PATH BODY: a POST from the process the office takes for Adaptive Link's daemon
    python3 - "$B" "$TMP/link.pid" "$1" "$2" <<'PHONE'
import os, sys, urllib.request
base, pidfile, path, body = sys.argv[1:]
open(pidfile, "w").write(str(os.getpid()))
req = urllib.request.Request(base + path, data=body.encode(), method="POST", headers={
    "Content-Type": "application/json", "X-Office": "1", "X-Office-Actor": "phone", "X-Office-Device": "phone1"})
try:
    print(urllib.request.urlopen(req, timeout=10).read().decode())
finally:
    open(pidfile, "w").write("0")
PHONE
}
as_phone "/api/inbox/$AID/ack" '{}' | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["state"] == "IN_PROGRESS" and d["acknowledged_by"] == "phone", d' || fail "acknowledge"
[ "$(MISSIONS)" = "$BEFORE" ] || fail "acknowledging an approval started work"
[ "$(code -X POST "${J[@]}" -d '{}' "$B/api/inbox/$AID/approve")" = 403 ] || fail "approved without the operator key"
[ "$(code -X POST "${J[@]}" -H 'X-Office-Actor: phone' -d '{}' "$B/api/inbox/$AID/approve")" = 403 ] || fail "the phone approved without the key"
[ "$(code -X POST "${J[@]}" "${OP[@]}" -d '{}' "$B/api/inbox/$AID/resolve")" = 409 ] || fail "an approval was closed by resolving it"
[ "$(MISSIONS)" = "$BEFORE" ] || fail "a refused approval started work"
post "${OP[@]}" -d '{}' "$B/api/inbox/$AID/approve" | python3 -c 'import json,sys; d=json.load(sys.stdin); r=d["result"]; assert d["item"]["state"] == "RESOLVED" and d["item"]["resolution"] == "approved" and r["approved_by"] == "operator" and r["created_by"] == "manager" and r["workflow_id"] == "move-robot", d' || fail "approve with the operator key"
[ "$(code -X POST "${J[@]}" "${OP[@]}" -d '{}' "$B/api/inbox/$AID/approve")" = 409 ] || fail "one approval ran twice"
[ "$(MISSIONS)" = "$((BEFORE + 1))" ] || fail "approval did not start exactly one mission"
# the event history: ordered, resumable from any point, UTC timestamps
curl -fsS "$B/api/journal?after=0&limit=1000" | python3 -c '
import json,sys; d=json.load(sys.stdin); s=[e["seq"] for e in d["events"]]; t=[e["type"] for e in d["events"]]
assert s == list(range(1, len(s) + 1)) and d["head"] == s[-1], s
assert "approval.requested" in t and "approval.granted" in t and "inbox.acknowledged" in t, t
assert all(e["ts_utc"].endswith("+00:00") for e in d["events"])' || fail "journal"
HEAD="$(curl -fsS "$B/api/journal?after=0&limit=1000" | python3 -c 'import json,sys; print(json.load(sys.stdin)["head"])')"
curl -fsS "$B/api/journal?after=$HEAD" | python3 -c 'import json,sys; assert json.load(sys.stdin)["events"] == []' || fail "journal after head"
# notifications: numbered, kept until delivered, confirmed per device, long-poll returns on time
NHEAD="$(curl -fsS "$B/api/notifications?after=0" | python3 -c 'import json,sys; d=json.load(sys.stdin); n=d["notifications"]; assert n and [x["id"] for x in n] == sorted(x["id"] for x in n) and any(x["priority"] == "critical" for x in n); print(d["head"])')" || fail "notifications"
curl -fsS "$B/api/notifications?after=0&channel=link" -H 'X-Office-Device: phone1' | python3 -c 'import json,sys; d=json.load(sys.stdin)["delivery"]; assert d["channel"] == "link:phone1" and d["pending"] >= 1, d' || fail "undelivered notifications"
[ "$(code -X POST "${J[@]}" -H 'X-Office-Device: phone1' -d "{\"channel\":\"link\",\"through\":$NHEAD}" "$B/api/notifications/delivered")" = 403 ] || fail "a keyless caller marked notifications delivered"
as_phone /api/notifications/delivered "{\"channel\":\"link\",\"through\":$NHEAD}" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["pending"] == 0 and d["channel"] == "link:phone1", d' || fail "delivery confirmation"
T0=$(date +%s%N)
curl -fsS "$B/api/notifications?after=$NHEAD&wait=1" | python3 -c 'import json,sys; assert json.load(sys.stdin)["notifications"] == []' || fail "long poll"
[ $(( ($(date +%s%N) - T0) / 1000000 )) -ge 900 ] || fail "long poll returned early"
post "${OP[@]}" -d "{\"through\":$NHEAD}" "$B/api/notifications/read" | python3 -c 'import json,sys; assert json.load(sys.stdin)["unread"] == 0' || fail "mark read"
[ "$(code -X POST "${J[@]}" -d '{}' "$B/api/inbox/$AID/bogus")" = 404 ] || fail "unknown inbox action"
curl -fsS "$B/api/state" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["journal_head"] >= 1 and "NEEDS_ATTENTION" in d["inbox"] and "head" in d["notifications"]' || fail "state carries the inbox"
# activity and report APIs
curl -fsS "$B/api/activity/agents" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert len(d) >= 2 and all({"id","status","task","mission","running_s","queued","blockers"} <= set(a) for a in d), d[0]' || fail "activity: assignments"
curl -fsS "$B/api/activity/summary" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["until"] - d["since"] == 86400 and all("active_s" in a and "idle_s" in a for a in d["agents"])' || fail "activity: summary"
curl -fsS "$B/api/activity/history?since=0&until=86400" | python3 -c 'import json,sys; assert json.load(sys.stdin) == []' || fail "activity: history range"
[ "$(code "$B/api/activity/summary?since=10&until=5")" = 400 ] || fail "activity: a backwards window was accepted"
# Milestone 3: the overview every view reads, and the chosen view kept in the office's database
curl -fsS "$B/api/overview" | python3 -c 'import json,sys; d=json.load(sys.stdin); c=d["counts"]; assert c["agents"] == len(d["agents"]) >= 2 and {"active","blocked","error","running_tasks","done_today","failed_today","running_missions"} <= set(c) and all(a["state"] in ("working","idle","blocked","error","paused") and a["state_label"] for a in d["agents"]) and "NEEDS_ATTENTION" in d["inbox"] and isinstance(d["missions"], list)' || fail "overview"
curl -fsS "$B/api/board" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert set(d["columns"]) == {"todo","doing","needs_you","done"} and d["agents"] and all("state" in a for a in d["agents"])' || fail "board"
curl -fsS "$B/api/ui" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["view"] == "office" and d["views"] == ["office", "command"], d' || fail "Virtual Office is not the default view"
post -d '{"view":"command"}' "$B/api/ui" >/dev/null || fail "pick the Command Center"
[ "$(code -X POST "${J[@]}" -d '{"view":"cockpit"}' "$B/api/ui")" = 400 ] || fail "an unknown view was accepted"
[ "$(code -X POST "${J[@]}" -H 'X-Office-Actor: manager' -d '{"view":"office"}' "$B/api/ui")" = 403 ] || fail "the manager changed the operator's view"
[ "$(code -X POST -H 'Content-Type: application/json' -d '{"view":"office"}' "$B/api/ui")" = 403 ] || fail "view change without X-Office header"
curl -fsS "$B/api/ui" | python3 -c 'import json,sys; assert json.load(sys.stdin)["view"] == "command"' || fail "view not kept"
OFFICE_STATE="$TMP/state" PYTHONPATH="$APP" python3 -c 'from office.config import DATA; from office.store import Store; assert Store(DATA / "office.db").get("ui.view") == "command"' || fail "view not saved in the database"
post -d '{"view":"office"}' "$B/api/ui" >/dev/null || fail "back to the Virtual Office"
curl -fsS "$B/api/tasks/$HTID/timing" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["task"]["id"] and "queue_s" in d and "approval_s" in d' || fail "task timing"
[ "$(code "$B/api/tasks/999999/timing")" = 404 ] || fail "timing of a missing task"
curl -fsS "$B/api/missions/$HMID/progress" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["mission"]["id"] and d["total_tasks"] >= 1 and "contributions" in d' || fail "mission progress"
curl -fsS "$B/api/reports/schedule" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["timezone"] == "Asia/Kolkata" and d["kinds"]["standup"]["time"] == "10:00" and d["kinds"]["evening"]["time"] == "19:00"' || fail "report schedule"
RID="$(post -d '{"kind":"standup"}' "$B/api/reports/generate" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["status"] == "generated" and d["manual"] == 1 and "on demand" in d["title"]; print(d["id"])')" || fail "report on demand"
curl -fsS "$B/api/reports/$RID" | python3 -c 'import json,sys; d=json.load(sys.stdin); m=d["markdown"]; assert m.startswith("# Morning standup (on demand") and "## By agent" in m and "## Decisions waiting for you" in m and d["data"]["plan"] is not None' || fail "report body"
post -d '{"kind":"evening"}' "$B/api/reports/generate" | python3 -c 'import json,sys; assert json.load(sys.stdin)["kind"] == "evening"' || fail "evening on demand"
curl -fsS "$B/api/reports?kind=standup" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d and "markdown" not in d[0]' || fail "report list"
[ "$(code -X POST "${J[@]}" -d '{"kind":"weekly"}' "$B/api/reports/generate")" = 400 ] || fail "unknown report kind"
# a ROS investigation saved as a workflow keeps its inputs, not its old snapshot, and captures a new one per run
post -d "{\"id\":\"replay-stall\",\"title\":\"Replay stall\",\"risk\":\"read\",\"from_mission\":$CMID}" "$B/api/workflows" | \
    python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["template"]["kind"] == "ros-investigation" and d["objective"] == "planner stalls in replay" and "snapshot" not in d["objective"], d' || fail "save ROS workflow from a mission"
RWID="$(post -d '{}' "$B/api/workflows/replay-stall/run" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert "ROS setup snapshot" in d["objective"] and "Recording comparison" in d["objective"] and d["workflow_id"] == "replay-stall"; print(d["id"])')" || fail "run ROS workflow"
curl -fsS "$B/api/capsules?mission_id=$RWID" | python3 -c "import json,sys; assert json.load(sys.stdin)" || fail "ROS workflow run captured no capsule"
# audit exports are private, complete and carry the governance facts and a checksum
post "$B/api/missions/$MID/export" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["path"] == sys.argv[1] + "/exports/mission-" + sys.argv[2] + ".json" and d["capsules"] == 1 and len(d["sha256"]) == 64' "$REC" "$MID" || fail "mission audit export"
post "$B/api/missions/$HMID/export" >/dev/null || fail "hardware mission export"
python3 - "$REC/exports/mission-$MID.json" "$REC/exports/mission-$HMID.json" <<'PY' || fail "audit bundle contents"
import hashlib, json, sys
for path in sys.argv[1:]:
    d = json.load(open(path))
    digest = d.pop("sha256")
    assert hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode()).hexdigest() == digest, path
h = json.load(open(sys.argv[2]))["policy"]
assert h["risk"] == "hardware" and h["approved_by"] == "operator" and h["workflow_id"] == "move-robot", h
PY
# retention: dry runs are free, deleting needs the operator, mission capsules are never deleted
SCID="$(post -d '{"command":"standalone"}' "$B/api/capsules" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')" || fail "standalone capsule"
python3 - "$REC/exports/mission-$MID.json" "$REC/capsules/$CID.json" "$REC/capsules/$SCID.json" <<'PY'
import os, sys, time
old = time.time() - 2 * 86400
for p in sys.argv[1:]:
    os.utime(p, (old, old))
PY
post -d '{"days":1,"kinds":["exports"]}' "$B/api/retention" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["count"] == 1 and not d["apply"]' || fail "retention preview"
[ -f "$REC/exports/mission-$MID.json" ] || fail "retention preview deleted a file"
[ "$(code -X POST "${J[@]}" -d '{"days":1,"apply":true}' "$B/api/retention")" = 403 ] || fail "retention deleted without the operator key"
post "${OP[@]}" -d '{"days":1,"apply":true}' "$B/api/retention" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["count"] == 2 and d["apply"] and d["kept_mission_capsules"] == 1, d' || fail "retention apply"
[ ! -e "$REC/exports/mission-$MID.json" ] && [ ! -e "$REC/capsules/$SCID.json" ] || fail "retention did not delete old records"
[ -f "$REC/capsules/$CID.json" ] || fail "retention deleted a mission's capsule"
curl -fsS "$B/api/health" | python3 -c 'import json,sys; assert json.load(sys.stdin)["missions"] == int(sys.argv[1])' "$(curl -fsS "$B/api/missions?limit=500" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')" || fail "health mission count"
# the office command: the owner's carries the key; one run under the manager never does, whatever its env says
OFFICE=(env OFFICE_STATE="$TMP/state" OFFICE_URL="$B" python3 "$APP/bin/office")
[ "$("${OFFICE[@]}" operator-key)" = "$KEY" ] || fail "office operator-key"
"${OFFICE[@]}" retention 1 --kind exports --apply >/dev/null || fail "owner's office retention --apply"
OFFICE_ACTOR=manager sh -c 'env -u OFFICE_ACTOR "$@"; exit $?' sh "${OFFICE[@]}" operator-key >/dev/null 2>&1 && fail "manager read the operator key through office"
OFFICE_ACTOR=manager sh -c 'env -u OFFICE_ACTOR "$@" 2>&1; true' sh "${OFFICE[@]}" retention 1 --apply | grep -q "operator key" || fail "manager deleted records through office"
OFFICE_ACTOR=manager sh -c 'env OFFICE_ACTOR=operator "$@" 2>&1; true' sh "${OFFICE[@]}" workflow run move-robot --approve | grep -q "operator key" || fail "manager approved a hardware run through office"
# agents reach the API over loopback, but nothing private: no key, no records, no approvals
mkdir -p "$SBX/state/company" "$SBX/state/data/mission-control/workflows"
echo secret > "$SBX/state/data/operator.key"
echo private > "$SBX/state/data/mission-control/workflows/private.json"
python3 - "$APP" "$SBX/state" "$B" <<'PY' || fail "agents can see or use operator-only things"
import os, subprocess, sys
os.environ["OFFICE_STATE"] = sys.argv[2]
sys.path.insert(0, sys.argv[1])
from office import agy
from office.config import COMPANY, DATA
probe = (f"test -d {COMPANY} && echo WORKSPACE; grep -q secret {DATA}/operator.key 2>/dev/null && echo LEAK; "
         f"find {DATA}/mission-control -type f -print -quit 2>/dev/null | grep -q . && echo LEAK; "
         f"curl -s -o /dev/null -w 'HTTP%{{http_code}}' -X POST -H 'X-Office: 1' -H 'Content-Type: application/json' "
         f"-d '{{\"approved\":true}}' {sys.argv[3]}/api/workflows/move-robot/run")
r = subprocess.run(agy._bwrap_prefix([]) + ["sh", "-c", probe], capture_output=True, text=True, env=agy._env("probe"))
assert "WORKSPACE" in r.stdout, f"the sandbox did not run: {r.stderr}"
assert "LEAK" not in r.stdout and r.stdout.strip().endswith("HTTP403"), r.stdout
PY
curl -fsS "$B/api/events?task_id=999&limit=4" | python3 -c 'import json,sys; assert json.load(sys.stdin) == []' || fail "task-filtered events"
[ -d "$TMP/state/company/projects" ] || fail "state folder layout"
curl -fsS "$B/api/study" | python3 -c 'import json,sys; json.load(sys.stdin)' || fail "study api"
[ "$(code -X POST -H 'X-Office: 1' "$B/api/study/nope/now")" = 400 ] || fail "unknown study program was accepted"
# providers: switching is validated, the token ledger keeps every provider apart
[ "$(code -X POST -H 'X-Office: 1' -H 'Content-Type: application/json' -d '{"provider":"nope"}' "$B/api/settings")" = 400 ] || fail "unknown provider was accepted"
curl -fsS "$B/api/state" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["providers"] and d["settings"]["provider"] in [p["id"] for p in d["providers"]]' || fail "providers in state"
mkdir -p "$TMP/state/data/usage"
echo '{"ts": 1700000000, "turn": 1700000000, "agent": "maya", "provider": "local", "model": "test", "kind": "chat", "fresh": 100, "cached": 0, "out": 20, "step": "answer"}' > "$TMP/state/data/usage/local.jsonl"
sleep 11   # one ledger scan
curl -fsS "$B/api/tokens?provider=local" | python3 -c '
import json, sys
d = json.load(sys.stdin)
loc = [p for p in d["providers"] if p["id"] == "local"]
assert loc and loc[0]["total"] == 120 and loc[0]["calls"] == 1, d["providers"]
assert d["totals"]["total"] == 120 and d["claude"]["calls"] == 0, d["totals"]
assert all(p["total"] == 0 for p in d["providers"] if p["id"] not in ("local", "claude")), "local usage leaked into another provider"' || fail "token ledger per provider"
# the sandbox: non-secret home files are writable; credentials/private state stay hidden; system stays read-only
mkdir -p "$SBX/home/Documents" "$SBX/home/.ssh" "$SBX/state/data"
echo original > "$SBX/home/Documents/note.txt"
echo credential > "$SBX/home/.ssh/id_ed25519"
echo credential > "$SBX/home/.env"
echo private > "$SBX/state/data/operator.key"
python3 - "$APP" "$SBX/state" "$SBX/home" <<'PY' || fail "agent sandbox home access"
import os, subprocess, sys
os.environ["OFFICE_STATE"] = sys.argv[2]
os.environ["HOME"] = sys.argv[3]
sys.path.insert(0, sys.argv[1])
from office import agy
home = os.path.expanduser("~")
doc = os.path.join(home, "Documents/note.txt")
hidden = [os.path.join(home, ".env")]
probe = (f"echo RAN; cat {doc}; echo changed >> {doc}; "
         f"grep -q credential {home}/.ssh/id_ed25519 2>/dev/null && echo LEAK; "
         f"grep -q credential {home}/.env 2>/dev/null && echo LEAK; "
         f"grep -q private {sys.argv[2]}/data/operator.key 2>/dev/null && echo LEAK; "
         "touch /usr/agent-office-write-probe 2>/dev/null && echo LEAK; true")
r = subprocess.run(agy._bwrap_prefix([], rw_dirs=[home], hidden=hidden) + ["sh", "-c", probe],
                   capture_output=True, text=True)
out = r.stdout
assert out.startswith("RAN"), f"the sandbox did not run: {r.stderr}"
assert "LEAK" not in out, out
assert "original" in out, out
assert open(doc).read().splitlines() == ["original", "changed"]
PY
# 3. The page itself in headless Chrome (skipped without Chrome)
if command -v google-chrome >/dev/null; then
    PYTHONPATH="$REPO/.local/office-pydeps" timeout 240 python3 "$REPO/scripts/verify-agent-office-ui.py" || fail "office page in Chrome"
else
    echo "skipped page checks: google-chrome is not installed"
fi
echo "agent office checks passed"
