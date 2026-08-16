#!/usr/bin/env bash
set -Eeuo pipefail

LOG="${HOME}/.cache/adaptive-files/preview-extension.log"

echo "===== PREVIEW EXTENSION LOG ====="
if [ -f "$LOG" ]; then
  cat "$LOG"
else
  echo "No log yet: $LOG"
fi

echo
echo "===== PROCESS ====="
PID="$(pgrep -n -x nautilus || true)"

if [ -z "$PID" ]; then
  echo "No Nautilus process is running."
  exit 0
fi

echo "$PID -> $(readlink -f "/proc/$PID/exe")"

echo
echo "===== LOADED MODULE ====="
grep -E 'libnautilus-python|nautilus-python' "/proc/$PID/maps" 2>/dev/null || true

echo
echo "===== ENVIRONMENT ====="
tr '\0' '\n' < "/proc/$PID/environ" \
  | grep -E '^(GTK_THEME|ADAPTIVE_FILES_|GI_TYPELIB_PATH|XDG_DATA_DIRS|PYTHONPATH)=' \
  || true
