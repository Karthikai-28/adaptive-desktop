#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
PREFIX="${REPO}/.local/adaptive-nautilus"
NEW_UUID="adaptive-shell-v16@local"
OLD_UUID="adaptive-shell@local"
LIVE="${HOME}/.local/share/gnome-shell/extensions/${NEW_UUID}"

echo "============================================================"
echo "1. SHELL MODULE"
echo "============================================================"

gnome-extensions info "$NEW_UUID" | sed -n '1,40p'

echo
echo "Old extension state:"
gnome-extensions info "$OLD_UUID" 2>/dev/null \
  | grep -E 'State|Enabled' \
  || true

test -f "${LIVE}/extension.js"
test -f "${LIVE}/stylesheet.css"
echo "PASS: new UUID files installed"

echo
echo "============================================================"
echo "2. FILE ROUTING"
echo "============================================================"

echo "inode/directory default:"
xdg-mime query default inode/directory || true

echo
echo "User Nautilus desktop override:"
grep -E '^(Name|Exec|Icon|DBusActivatable)=' \
  "${HOME}/.local/share/applications/org.gnome.Nautilus.desktop"

echo
echo "Launcher self-test:"
"${REPO}/scripts/adaptive-files-launch-v1.6.sh" --self-test

echo
echo "============================================================"
echo "3. TOP CLOCK"
echo "============================================================"

grep -q "_restoreGNOMEClock" "${LIVE}/extension.js"
echo "PASS: v1.6 explicitly restores GNOME dateMenu"

echo "GNOME clock configuration:"
gsettings get org.gnome.desktop.interface clock-format || true
gsettings get org.gnome.desktop.interface clock-show-date || true
gsettings get org.gnome.desktop.interface clock-show-weekday || true

echo
echo "============================================================"
echo "4. OVERVIEW"
echo "============================================================"

grep -q "#dash" "${LIVE}/stylesheet.css"
echo "PASS: stock bottom dash suppression installed"

grep -q "#overviewGroup" "${LIVE}/stylesheet.css"
echo "PASS: Adaptive overview styling installed"

echo
echo "============================================================"
echo "5. SHELL LOG"
echo "============================================================"

journalctl --user -b --no-pager 2>/dev/null \
  | grep -F "[Adaptive Shell v1.6]" \
  | tail -40 \
  || true

echo
echo "============================================================"
echo "MANUAL TEST"
echo "============================================================"
echo
echo "A. Press Super:"
echo "   - bottom Ubuntu dash should be gone"
echo "   - left Adaptive rail should remain"
echo
echo "B. Click left Files icon:"
echo "   - Adaptive dark File Explorer should open"
echo "   - right Inspector should be available"
echo
echo "C. Click the normal Ubuntu Files app icon/search result:"
echo "   - it should ALSO route to Adaptive Files"
echo
echo "D. Click Settings at bottom-left:"
echo "   - GNOME Settings should open"
echo
echo "E. Check top center:"
echo "   - GNOME time should be visible"
echo "   - clicking it should open calendar/notifications"
