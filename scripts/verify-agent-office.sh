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
used = [a["desk"] for a in cfg["agents"]]
assert len(used) == len(set(used)), "two agents share a desk"
print(f"roster ok: {len(ids)} agents + {cfg['manager']['name']}")
PY
[ "$QUICK" = 1 ] && { echo "quick checks passed"; exit 0; }

# 2. A throwaway server: API, guards, path traversal
PYTHONPATH="$REPO/.local/office-pydeps" python3 -c "import fastapi, uvicorn" 2>/dev/null ||
    { echo "skipped server checks: run scripts/install-agent-office.sh first"; exit 0; }
PORT=8799
OFFICE_STATE="$TMP/state" OFFICE_PORT=$PORT PYTHONPATH="$REPO/.local/office-pydeps" \
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
echo "agent office checks passed"
