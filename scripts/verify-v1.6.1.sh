#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
PREFIX="${REPO}/.local/adaptive-nautilus"
NEW_UUID="adaptive-shell-v16@local"
OLD_UUID="adaptive-shell@local"
LIVE="${HOME}/.local/share/gnome-shell/extensions/${NEW_UUID}"

echo "============================================================"
echo "1. NEW SHELL UUID"
echo "============================================================"

if ! gnome-extensions info \
  "$NEW_UUID" \
  >/dev/null 2>&1
then
  echo "FAIL: current GNOME Shell does not know $NEW_UUID"
  echo
  echo "If install-v1.6.1.sh asked for a logout/login, do that first."
  exit 11
fi

gnome-extensions info "$NEW_UUID" \
  | sed -n '1,45p'

echo
echo "Old extension:"
gnome-extensions info "$OLD_UUID" 2>/dev/null \
  | sed -n '1,25p' \
  || true

echo
echo "Enabled extension setting:"
gsettings get \
  org.gnome.shell \
  enabled-extensions

echo
echo "============================================================"
echo "2. FILES ROUTING"
echo "============================================================"

echo "inode/directory:"
xdg-mime query default inode/directory

echo
echo "Per-user standard Files entry:"
grep -E \
  '^(Name|Exec|Icon|DBusActivatable)=' \
  "${HOME}/.local/share/applications/org.gnome.Nautilus.desktop"

grep -q \
  'adaptive-files-launch-v1.6.sh' \
  "${HOME}/.local/share/applications/org.gnome.Nautilus.desktop"

echo "PASS: standard Files desktop ID routes to Adaptive Files"

echo
echo "Launcher:"
"${REPO}/scripts/adaptive-files-launch-v1.6.sh" \
  --self-test

echo
echo "============================================================"
echo "3. WORKING DOCK CODE"
echo "============================================================"

grep -q \
  'adaptive-files-launch-v1.6.sh' \
  "${LIVE}/extension.js"
echo "PASS: Files dock route"

grep -q \
  'gnome-control-center' \
  "${LIVE}/extension.js"
echo "PASS: Settings dock route"

grep -q \
  'showApps' \
  "${LIVE}/extension.js"
echo "PASS: Applications dock route"

grep -q \
  'Gio.Subprocess.new' \
  "${LIVE}/extension.js"
echo "PASS: GIO process launcher"

echo
echo "============================================================"
echo "4. CLOCK / OVERVIEW"
echo "============================================================"

grep -q \
  '_restoreGNOMEClock' \
  "${LIVE}/extension.js"
echo "PASS: real GNOME dateMenu restoration"

grep -q '#dash' \
  "${LIVE}/stylesheet.css"
echo "PASS: stock Overview dash suppression"

grep -q '#overviewGroup' \
  "${LIVE}/stylesheet.css"
echo "PASS: Adaptive Overview styling"

echo
echo "============================================================"
echo "5. RUNTIME LOG"
echo "============================================================"

journalctl --user -b --no-pager 2>/dev/null \
  | grep -F '[Adaptive Shell v1.6]' \
  | tail -50 \
  || true

echo
echo "============================================================"
echo "MANUAL ACCEPTANCE TEST"
echo "============================================================"
echo
echo "A. Top bar:"
echo "   Time must be visible."
echo "   Clicking it must open GNOME calendar/notifications."
echo
echo "B. Super / Overview:"
echo "   Stock bottom dash must be gone."
echo "   Adaptive left rail must remain."
echo
echo "C. Click Files in left rail:"
echo "   Adaptive dark Files + Inspector must open."
echo
echo "D. Open the normal 'Files' app:"
echo "   It must route to the same Adaptive Files."
echo
echo "E. Click Settings:"
echo "   GNOME Settings must open."
