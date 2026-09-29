#!/usr/bin/env bash
set -Eeuo pipefail

#
# Checks that the Adaptive session's file manager is wired up.
#
# Replaces the old adaptive-files-launch-v1.6.sh self-test. There is no
# launcher any more: the forked Nautilus is activated the same way Ubuntu
# activates its own, so what needs verifying is the fork itself plus the
# activation files that point at it.
#

REPO="${HOME}/adaptive-desktop"
PREFIX="${REPO}/.local/adaptive-nautilus"
BIN="${PREFIX}/bin/nautilus"
DISPATCH="${REPO}/scripts/adaptive-files-dispatch.sh"
SERVICE_DIR="${HOME}/.local/share/dbus-1/services"

pass() {
  printf 'PASS: %s\n' "$*"
}

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

echo "===== ADAPTIVE FILES STACK ====="

test -x "$BIN" || fail "forked Nautilus binary missing: $BIN"
pass "forked Nautilus binary"

test -f "${PREFIX}/share/applications/org.gnome.Nautilus.desktop" \
  || fail "fork desktop entry missing"
pass "fork desktop entry"

test -f "${XDG_DATA_HOME:-$HOME/.local/share}/themes/Adaptive/gtk-3.0/gtk.css" \
  || fail "Adaptive GTK theme missing (run ./scripts/install-adaptive-theme.sh)"
pass "Adaptive GTK theme"

test -f "${PREFIX}/share/adaptive-files/preview.css" \
  || fail "Files stylesheet missing (run ./scripts/install-files-extension.sh)"
pass "Files stylesheet"

test -f "${PREFIX}/share/icons/AdaptiveFilesIcons/index.theme" \
  || fail "AdaptiveFilesIcons missing"
pass "AdaptiveFilesIcons"

test -f "${PREFIX}/share/nautilus-python/extensions/adaptive_preview.py" \
  || fail "preview extension missing"
pass "preview extension"

test -x "$DISPATCH" || fail "session dispatcher missing: $DISPATCH"
bash -n "$DISPATCH"
pass "session dispatcher"

for name in org.gnome.Nautilus org.freedesktop.FileManager1; do
  service="${SERVICE_DIR}/${name}.service"
  test -f "$service" || fail "activation file missing: $service"
  grep -q "Exec=${DISPATCH}" "$service" \
    || fail "$service does not point at the dispatcher"
  pass "activation: $name"
done

# The fork must own the app id it is activated under, otherwise stock Nautilus
# and this build fight over the same bus name.
grep -q '#define APPLICATION_ID "org.gnome.Nautilus"' \
  "${REPO}/build/adaptive-nautilus/config.h" \
  || fail "fork was built with a different APPLICATION_ID"
pass "fork owns org.gnome.Nautilus"

# Retiring the standalone app left its desktop entry registered as the folder
# handler, pointing at a launcher that no longer existed. Assert on both
# resolvers: apps go through GIO, while xdg-mime applies its own precedence.
EXPECTED="org.gnome.Nautilus.desktop"

actual_xdg="$(xdg-mime query default inode/directory 2>/dev/null || true)"
test "$actual_xdg" = "$EXPECTED" \
  || fail "xdg-mime folder handler is '$actual_xdg', expected $EXPECTED"
pass "xdg-mime folder handler"

gio mime inode/directory 2>/dev/null | grep -q "$EXPECTED" \
  || fail "GIO folder handler is not $EXPECTED"
pass "GIO folder handler"

echo
echo "Adaptive Files stack verified."
