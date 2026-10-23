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
    assert pv.get("engine") in ("agy", "ollama", "codex", "claude") and pv.get("model"), f"provider {pid}: needs engine agy|ollama|codex|claude and a model"
    assert "@" not in pid and pid != "claude", f"provider id {pid!r} is reserved or invalid"
assert any(pv["engine"] == "agy" for pv in provs.values()), "keep one agy (Gemini) provider"
planner = m.get("planner_provider", "codex")
assert planner in provs and provs[planner]["engine"] == "codex", "manager planner_provider must be Codex"
assert m.get("planner_reasoning", "medium") in ("low", "medium", "high"), "invalid planner_reasoning"
for k in ("provider", "fallback"):
    assert not cfg.get(k) or cfg[k] in provs, f"{k} {cfg.get(k)!r} is not a provider"
for a in cfg["agents"]:
    assert not a.get("provider") or a["provider"] in provs, f"{a['id']}: unknown provider {a['provider']}"
used = [a["desk"] for a in cfg["agents"]]
assert len(used) == len(set(used)), "two agents share a desk"
print(f"roster ok: {len(ids)} agents + {cfg['manager']['name']}; providers: {', '.join(provs)}")
PY
OFFICE_STATE="$TMP/plan-gate" PYTHONPATH="$APP" python3 - <<'PY' || fail "manager plan gate"
from office.codex import CodexRun, TALK_ONLY
from office.manager import NO_WORK_PLAN, PLAN_GATE, WORK_PLAN, _plan_marker

assert _plan_marker(f"{WORK_PLAN}\n- task") == WORK_PLAN
assert _plan_marker(f"\n{NO_WORK_PLAN}\nanswer") == NO_WORK_PLAN
assert not _plan_marker("Here is a plan without the required gate")
assert PLAN_GATE.startswith("[office")
run = CodexRun("plan", agent_name="Codex Planner", agent_id="planner", provider="codex",
               cfg={"model": "test", "web_search": False}, tools=False, reasoning="medium")
cmd = run._cmd()
assert all(any(x == f or x.endswith(f"={f}") for x in cmd) for f in TALK_ONLY), cmd
assert 'sandbox_mode="read-only"' in cmd and 'web_search="disabled"' in cmd, cmd
assert not any("permissions.office.filesystem" in x for x in cmd), cmd
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
    ("claude-gpt", "week", 42), ("claude-gpt", "5h", None),
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
    async def plan(prompt, kind): return "NO_WORK_PLAN\nnothing to dispatch", ""
    async def turn(prompt, kind): return "manager reply", ""
    o.manager._codex_plan, o.manager._turn = plan, turn
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

asyncio.run(main())
PY
PORT=8799
OFFICE_STATE="$TMP/state" OFFICE_PORT=$PORT OFFICE_NO_STUDY=1 OFFICE_NO_REPO_SCAN=1 \
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
[ "$(code -X POST -H 'X-Office: 1' -H 'Content-Type: application/json' -d '{"autopilot":false,"paused":true}' "$B/api/settings")" = 200 ] || fail "settings"
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
python3 - "$APP" "$SBX/state" "$B" <<'PY' || fail "agents can see or use operator-only things"
import os, subprocess, sys
os.environ["OFFICE_STATE"] = sys.argv[2]
sys.path.insert(0, sys.argv[1])
from office import agy
from office.config import COMPANY, DATA
probe = (f"test -d {COMPANY} && echo WORKSPACE; test -e {DATA}/operator.key && echo LEAK; "
         f"test -e {DATA}/mission-control && echo LEAK; "
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
curl -fsS "$B/api/tokens/agent/planner" | python3 -c 'import json,sys; assert json.load(sys.stdin)["summary"]["total"] == 0' || fail "planner token view"
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
# the sandbox: an empty home with only tools, the workspace and assigned repos; nothing personal
python3 - "$APP" "$SBX/state" <<'PY' || fail "agent sandbox exposes too much"
import os, subprocess, sys
os.environ["OFFICE_STATE"] = sys.argv[2]
sys.path.insert(0, sys.argv[1])
from office import agy
home = os.path.expanduser("~")
probe = os.path.join(home, "Documents")
r = subprocess.run(agy._bwrap_prefix([]) + ["sh", "-c", f"echo RAN; ls -A {home}; test -e {probe} && echo LEAK; touch /usr/x 2>/dev/null && echo LEAK; true"],
                   capture_output=True, text=True)
out = r.stdout
assert out.startswith("RAN"), f"the sandbox did not run: {r.stderr}"
assert "LEAK" not in out, out
assert not {"Documents", ".ssh", ".claude", ".gnupg"} & set(out.split()), out
PY
# 3. The page itself in headless Chrome (skipped without Chrome)
if command -v google-chrome >/dev/null; then
    PYTHONPATH="$REPO/.local/office-pydeps" timeout 240 python3 "$REPO/scripts/verify-agent-office-ui.py" || fail "office page in Chrome"
else
    echo "skipped page checks: google-chrome is not installed"
fi
echo "agent office checks passed"
