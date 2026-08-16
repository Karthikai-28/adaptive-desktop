#!/usr/bin/env bash
set -Eeuo pipefail

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

pass() {
  echo "PASS: $*"
}

UBUNTU_SESSION="/usr/share/xsessions/ubuntu.desktop"
ADAPTIVE_SESSION="/usr/share/xsessions/adaptive-desktop.desktop"
WRAPPER="/usr/local/bin/adaptive-desktop-session"
PROFILE="/etc/dconf/profile/adaptive"

test -f "$UBUNTU_SESSION" || fail "normal Ubuntu session entry missing"
pass "normal Ubuntu session remains registered"

test -f "$ADAPTIVE_SESSION" || fail "Adaptive session entry missing"
grep -q '^Name=Adaptive Desktop$' "$ADAPTIVE_SESSION" || fail "Adaptive session name mismatch"
grep -q '^Exec=/usr/local/bin/adaptive-desktop-session$' "$ADAPTIVE_SESSION" || fail "Adaptive session Exec mismatch"
pass "Adaptive GDM session entry is valid"

test -x "$WRAPPER" || fail "Adaptive session wrapper missing or not executable"
grep -q '^export DCONF_PROFILE=adaptive$' "$WRAPPER" || fail "wrapper does not export DCONF_PROFILE=adaptive"
grep -q 'gnome-session --session=ubuntu' "$WRAPPER" || fail "wrapper does not reuse Ubuntu GNOME session"
pass "Adaptive wrapper isolates dconf and reuses Ubuntu session"

test -f "$PROFILE" || fail "Adaptive dconf profile missing"
head -1 "$PROFILE" | grep -q '^user-db:adaptive$' || fail "Adaptive dconf profile does not use user-db:adaptive first"
pass "Adaptive dconf profile is separate"

if [[ "${DCONF_PROFILE:-}" == "adaptive" ]]; then
  pass "current process is inside Adaptive dconf profile"
else
  echo "INFO: current process DCONF_PROFILE is '${DCONF_PROFILE:-unset}', expected outside Adaptive session during normal development"
fi

echo "Session isolation verification complete."
