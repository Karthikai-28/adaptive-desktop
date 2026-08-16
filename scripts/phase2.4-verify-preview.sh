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

echo "===== ADAPTIVE FILES v1.3 ====="
"$BIN" --version

echo
echo "===== INSPECTOR ====="
grep -E "Inspector attached" "$LOG" 2>/dev/null | tail -5 || true

echo
echo "===== FOLDER PREVIEW ====="
grep -E "Folder preview (start|complete|worker failed)" "$LOG" 2>/dev/null \
  | tail -20 || true

echo
echo "===== CSS ERRORS ====="
if grep -q "gtk-css-provider-error" "$LOG" 2>/dev/null; then
  echo "FAIL"
  grep -A4 -B2 "gtk-css-provider-error" "$LOG" | tail -40
else
  echo "PASS: none"
fi

echo
echo "===== LOCAL PROCESS ====="
PIDS="$(find_adaptive_pids || true)"
if [ -z "$PIDS" ]; then
  echo "No running local Adaptive Files process."
else
  for pid in $PIDS; do
    echo "$pid -> $(readlink -f "/proc/$pid/exe")"
  done
fi

echo
echo "===== LAST LOG ====="
tail -120 "$LOG" 2>/dev/null || true
