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
cleanup() { [ -n "$SERVER" ] && kill "$SERVER" 2>/dev/null; rm -rf "$TMP"; }
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
    assert pv.get("engine") in ("agy", "ollama", "codex") and pv.get("model"), f"provider {pid}: needs engine agy|ollama|codex and a model"
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
[ "$QUICK" = 1 ] && { echo "quick checks passed"; exit 0; }

# 2. A throwaway server: API, guards, path traversal
PYTHONPATH="$REPO/.local/office-pydeps" python3 -c "import fastapi, uvicorn" 2>/dev/null ||
    { echo "skipped server checks: run scripts/install-agent-office.sh first"; exit 0; }
PORT=8799
OFFICE_STATE="$TMP/state" OFFICE_PORT=$PORT OFFICE_NO_STUDY=1 PYTHONPATH="$REPO/.local/office-pydeps" \
    python3 "$APP/server.py" >"$TMP/server.log" 2>&1 &
SERVER=$!
for _ in $(seq 1 40); do curl -fsS -o /dev/null "http://127.0.0.1:$PORT/api/state" 2>/dev/null && break; sleep 0.25; done
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
B="http://127.0.0.1:$PORT"
[ "$(code "$B/api/state")" = 200 ] || { cat "$TMP/server.log"; fail "server did not start"; }
[ "$(code "$B/")" = 200 ] || fail "page"
[ "$(code "$B/static/app.js")" = 200 ] || fail "static files"
[ "$(code -X POST -H 'Content-Type: application/json' -d '{}' "$B/api/settings")" = 403 ] || fail "POST without X-Office header was accepted"
[ "$(code -X POST -H 'X-Office: 1' -H 'Origin: http://evil.example' -H 'Content-Type: application/json' -d '{}' "$B/api/settings")" = 403 ] || fail "cross-site POST was accepted"
[ "$(code -H 'Host: evil.example' "$B/api/state")" = 403 ] || fail "foreign Host header was accepted"
[ "$(code "$B/api/files?path=../../..")" = 403 ] || fail "path traversal out of the workspace"
[ "$(code -X POST -H 'X-Office: 1' -H 'Content-Type: application/json' -d '{"agent":"nobody","title":"x"}' "$B/api/tasks")" = 400 ] || fail "task for an unknown agent was accepted"
[ "$(code -X POST -H 'X-Office: 1' -H 'Content-Type: application/json' -d '{"autopilot":false}' "$B/api/settings")" = 200 ] || fail "settings"
curl -fsS "$B/api/state" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert len(d["roster"]) >= 2 and d["settings"]["autopilot"] is False' || fail "state"
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
# the sandbox: an empty home with only tools, the workspace and assigned repos; nothing personal
python3 - "$APP" "$TMP/state" <<'PY' || fail "agent sandbox exposes too much"
import os, subprocess, sys
os.environ["OFFICE_STATE"] = sys.argv[2]
sys.path.insert(0, sys.argv[1])
from office import agy
home = os.path.expanduser("~")
probe = os.path.join(home, "Documents")
out = subprocess.run(agy._bwrap_prefix([]) + ["sh", "-c", f"ls -A {home}; test -e {probe} && echo LEAK; touch /usr/x 2>/dev/null && echo LEAK; true"],
                     capture_output=True, text=True).stdout
assert "LEAK" not in out, out
assert not {"Documents", ".ssh", ".claude", ".gnupg"} & set(out.split()), out
PY
echo "agent office checks passed"
