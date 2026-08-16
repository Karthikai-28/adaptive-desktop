#!/usr/bin/env bash
set -Eeuo pipefail

UUID="adaptive-shell-v16@local"
LIVE="${HOME}/.local/share/gnome-shell/extensions/${UUID}/stylesheet.css"

echo "===== CALENDAR CENTER v1.6.2 ====="

test -f "$LIVE"

grep -q \
  'Adaptive Calendar Center v1.6.2' \
  "$LIVE"
echo "PASS: visual layer installed"

for selector in \
  '.calendar-menu .popup-menu-content' \
  '.message-list' \
  '.dnd-button' \
  '.datemenu-calendar-column' \
  '.datemenu-today-button' \
  '.calendar-today' \
  '.events-button'
do
  grep -Fq "$selector" "$LIVE"
  echo "PASS: $selector"
done

echo
echo "Extension:"
gnome-extensions info "$UUID" \
  | sed -n '1,35p'

echo
echo "Manual check:"
echo "  1. Click top time."
echo "  2. Today must be blue/cyan, not orange."
echo "  3. Empty notification area must look intentional/compact."
echo "  4. DND switch must match Adaptive colors."
echo "  5. Event card must use dark-blue Adaptive surface."
echo "  6. Calendar behavior/appointments/notifications must still work."
