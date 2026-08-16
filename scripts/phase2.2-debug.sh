#!/usr/bin/env bash
set -Eeuo pipefail

LOG="${HOME}/.cache/adaptive-files/preview-extension.log"

echo "===== EXTENSION LOG ====="
cat "$LOG" 2>/dev/null || true

echo
echo "===== RUNNING NAUTILUS ====="
for pid in $(pgrep -x nautilus 2>/dev/null || true); do
  echo "$pid -> $(readlink -f "/proc/$pid/exe" 2>/dev/null || true)"
  echo "-- extension loader --"
  grep -E 'libnautilus-python|nautilus-python' "/proc/$pid/maps" 2>/dev/null \
    | head -10 || true
  echo "-- adaptive environment --"
  tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null \
    | grep -E '^(GTK_THEME|ADAPTIVE_FILES_|XDG_DATA_DIRS|GI_TYPELIB_PATH)=' \
    || true
done
