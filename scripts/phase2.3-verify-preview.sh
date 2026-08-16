#!/usr/bin/env bash
set -Eeuo pipefail

PREFIX="${HOME}/adaptive-desktop/.local/adaptive-nautilus"
BIN="${PREFIX}/bin/nautilus"
LOG="${HOME}/.cache/adaptive-files/preview-extension.log"

find_adaptive_pids() {
  for proc in /proc/[0-9]*; do
    [ -e "$proc/exe" ] || continue
    exe="$(readlink -f "$proc/exe" 2>/dev/null || true)"
    if [ "$exe" = "$BIN" ]; then
      echo "${proc##*/}"
    fi
  done
}

echo "===== BINARY ====="
"$BIN" --version

echo
echo "===== CSS ====="
if grep -q "gtk-css-provider-error" "$LOG" 2>/dev/null; then
  echo "FAIL: GTK CSS parser error exists."
else
  echo "PASS: no GTK CSS parser error logged."
fi

echo
echo "===== LOCATION PROVIDER ====="
grep -E "LocationWidgetProvider active" "$LOG" 2>/dev/null | tail -3 || true

echo
echo "===== ATTACHMENT ATTEMPTS ====="
grep -E "Inspector attach attempt|Inspector attached|No suitable overlay|Failed while attaching" \
  "$LOG" 2>/dev/null | tail -40 || true

echo
echo "===== CUSTOM ICON THEME ====="
test -f "${PREFIX}/share/icons/AdaptiveFilesIcons/index.theme"
echo "PASS: AdaptiveFilesIcons installed."

echo
echo "===== LOCAL ADAPTIVE FILES PROCESS ====="
PIDS="$(find_adaptive_pids || true)"
if [ -z "$PIDS" ]; then
  echo "No process with executable:"
  echo "  $BIN"
else
  for pid in $PIDS; do
    echo "$pid -> $(readlink -f "/proc/$pid/exe")"
    echo "comm: $(cat "/proc/$pid/comm" 2>/dev/null || true)"
    echo "-- extension loader --"
    grep -E 'libnautilus-python|nautilus-python' "/proc/$pid/maps" 2>/dev/null \
      | head -5 || true
  done
fi

echo
echo "===== EXTENSION LOG ====="
tail -140 "$LOG" 2>/dev/null || true
