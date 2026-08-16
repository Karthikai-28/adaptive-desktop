#!/usr/bin/env bash
set -Eeuo pipefail

LIVE="${HOME}/.local/share/gnome-shell/extensions/adaptive-shell@local"

echo "STEP 4 — TOP CLOCK / CALENDAR"
echo

grep -q "_restoreAndStyleStockClock" "${LIVE}/extension.js"
echo "PASS: extension explicitly restores GNOME dateMenu"

grep -q "adaptive-stock-clock" "${LIVE}/stylesheet.css"
echo "PASS: Adaptive clock styling installed"

echo
echo "Current GNOME clock settings:"
gsettings get org.gnome.desktop.interface clock-format || true
gsettings get org.gnome.desktop.interface clock-show-date || true
gsettings get org.gnome.desktop.interface clock-show-weekday || true

echo
echo "Manual verification:"
echo "  1. Time is visible in the top bar."
echo "  2. Click it."
echo "  3. GNOME calendar/notifications menu opens normally."
