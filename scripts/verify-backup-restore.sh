#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
STATE_DIR="$(mktemp -d -t adaptive-session-state-XXXXXX)"
STATE="${STATE_DIR}/session-state.json"
trap 'rm -rf "$STATE_DIR"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

pass() {
  echo "PASS: $*"
}

test -d "${REPO}/backups" || fail "backups directory missing"
backup_count="$(find "${REPO}/backups" -maxdepth 1 -mindepth 1 -type d | wc -l | tr -d ' ')"
(( backup_count > 0 )) || fail "no backup snapshots found"
pass "backup inventory contains ${backup_count} snapshots"

ADAPTIVE_STATE_DIR="$STATE_DIR" "${REPO}/scripts/session-cli.py" save
test -s "$STATE" || fail "session state was not saved"
python3 -m json.tool "$STATE" >/dev/null
pass "session state saved and is valid JSON"

recover_output="$("${REPO}/scripts/session-cli.py" recover)"
grep -q "gnome-extensions disable adaptive-shell@local" <<<"$recover_output" \
  || fail "recover output does not disable Adaptive Shell"
grep -q "remove-adaptive-session.sh" <<<"$recover_output" \
  || fail "recover output does not include Adaptive session removal"
grep -q "Choose Ubuntu from the GDM gear menu" <<<"$recover_output" \
  || fail "recover output does not include Ubuntu fallback session"
pass "recovery command plan is present"

grep -q "systemctl restart gdm3" "${REPO}/docs/RECOVERY_RUNBOOK.md" \
  || fail "recovery runbook missing GDM restart step"
pass "recovery runbook includes GDM restart path"

echo "Backup/restore readiness verified."
