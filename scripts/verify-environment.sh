#!/usr/bin/env bash
set -Eeuo pipefail

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

pass() {
  echo "PASS: $*"
}

source /etc/os-release

[[ "${ID:-}" == "ubuntu" ]] || fail "expected Ubuntu, got ${ID:-unknown}"
[[ "${VERSION_ID:-}" == "22.04" ]] || fail "expected Ubuntu 22.04, got ${VERSION_ID:-unknown}"
pass "Ubuntu ${VERSION_ID}"

gnome-shell --version | grep -q ' 42\.' || fail "expected GNOME Shell 42"
pass "$(gnome-shell --version)"

command -v gnome-session >/dev/null || fail "gnome-session missing"
command -v gnome-extensions >/dev/null || fail "gnome-extensions missing"
command -v gsettings >/dev/null || fail "gsettings missing"
command -v xdg-mime >/dev/null || fail "xdg-mime missing"
pass "required desktop commands exist"

test -f /usr/share/xsessions/ubuntu.desktop || fail "Ubuntu X11 session missing"
pass "normal Ubuntu session entry exists"

free_kb="$(df --output=avail / | tail -1 | tr -d ' ')"
free_gb=$((free_kb / 1024 / 1024))
(( free_gb >= 10 )) || fail "less than 10 GB free on /"
pass "root filesystem has approximately ${free_gb} GB free"

test -d "${HOME}/adaptive-desktop/.git" || fail "repo git directory missing"
pass "Adaptive Desktop repo exists"

echo "Environment verification complete."
