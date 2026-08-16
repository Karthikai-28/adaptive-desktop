#!/usr/bin/env bash
set -Eeuo pipefail

PREFIX="${HOME}/adaptive-desktop/.local/adaptive-nautilus"
LOG="${HOME}/.cache/adaptive-files/preview-extension.log"

echo "===== BINARY ====="
"${PREFIX}/bin/nautilus" --version

echo
echo "===== CSS ERROR CHECK ====="
if grep -q "gtk-css-provider-error" "$LOG" 2>/dev/null; then
  echo "FAIL: GTK CSS parser reported an error."
  tail -60 "$LOG"
else
  echo "PASS: no GTK CSS parser error logged."
fi

echo
echo "===== LOCATION PROVIDER ====="
if grep -q "LocationWidgetProvider active" "$LOG" 2>/dev/null; then
  echo "PASS: location hook executed."
else
  echo "WAITING: no location hook recorded yet."
fi

echo
echo "===== INSPECTOR ATTACHMENT ====="
grep -E "Inspector attached|No suitable overlay" "$LOG" 2>/dev/null \
  | tail -20 || true

echo
echo "===== ICON THEME ====="
test -f "${PREFIX}/share/icons/AdaptiveFilesIcons/index.theme"
echo "PASS: AdaptiveFilesIcons installed."

echo
echo "===== PROCESS ====="
for pid in $(pgrep -x nautilus 2>/dev/null || true); do
  echo "$pid -> $(readlink -f "/proc/$pid/exe" 2>/dev/null || true)"
done

echo
echo "===== LOG ====="
tail -100 "$LOG" 2>/dev/null || true
