#!/usr/bin/env bash
set -Eeuo pipefail

PREFIX="${HOME}/adaptive-desktop/.local/adaptive-nautilus"
BIN="${PREFIX}/bin/nautilus"
LOG="${HOME}/.cache/adaptive-files/preview-extension.log"

echo "===== FULL PREVIEW LOG ====="
cat "$LOG" 2>/dev/null || true

echo
echo "===== PROCESSES USING LOCAL BINARY ====="
found=0
for proc in /proc/[0-9]*; do
  [ -e "$proc/exe" ] || continue
  exe="$(readlink -f "$proc/exe" 2>/dev/null || true)"

  if [ "$exe" = "$BIN" ]; then
    found=1
    pid="${proc##*/}"
    echo "$pid -> $exe"
    echo "comm: $(cat "$proc/comm" 2>/dev/null || true)"
    echo "-- adaptive environment --"
    tr '\0' '\n' < "$proc/environ" 2>/dev/null \
      | grep -E '^(GTK_THEME|ADAPTIVE_FILES_|XDG_DATA_DIRS|GI_TYPELIB_PATH)=' \
      || true
    echo "-- python extension module --"
    grep -E 'libnautilus-python|nautilus-python' "$proc/maps" 2>/dev/null \
      | head -10 || true
  fi
done

if [ "$found" -eq 0 ]; then
  echo "No running process resolves to:"
  echo "  $BIN"
fi
