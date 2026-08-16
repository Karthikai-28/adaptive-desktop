#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
PREFIX="${REPO}/.local/adaptive-nautilus"
BIN="${PREFIX}/bin/nautilus"
CSS="${PREFIX}/share/adaptive-files/preview.css"
LOG_DIR="${HOME}/.cache/adaptive-files"
LAUNCH_LOG="${LOG_DIR}/launcher-v1.6.log"

mkdir -p "$LOG_DIR"

log() {
  printf '[%s] %s\n' "$(date '+%F %T')" "$*" \
    | tee -a "$LAUNCH_LOG"
}

self_test() {
  echo "===== ADAPTIVE FILES v1.6 SELF-TEST ====="

  test -x "$BIN"
  echo "PASS: local Nautilus binary"

  test -f "${PREFIX}/share/themes/AdaptiveFiles/gtk-3.0/gtk.css"
  echo "PASS: AdaptiveFiles GTK theme"

  test -f "${PREFIX}/share/icons/AdaptiveFilesIcons/index.theme"
  echo "PASS: AdaptiveFilesIcons"

  test -f "${PREFIX}/share/nautilus-python/extensions/adaptive_preview.py"
  echo "PASS: preview extension"

  test -f "$CSS"
  echo "PASS: preview CSS"

  echo
  echo "inode/directory default:"
  xdg-mime query default inode/directory || true
}

if [ "${1:-}" = "--self-test" ]; then
  self_test
  exit 0
fi

if [ ! -x "$BIN" ]; then
  log "ERROR: missing local binary: $BIN"
  exit 2
fi

LOCAL_RUNNING=0
STOCK_PIDS=()

for proc in /proc/[0-9]*; do
  [ -e "$proc/exe" ] || continue

  exe="$(
    readlink -f "$proc/exe" 2>/dev/null || true
  )"

  if [ "$exe" = "$BIN" ]; then
    LOCAL_RUNNING=1
  elif [ "$exe" = "/usr/bin/nautilus" ]; then
    STOCK_PIDS+=("${proc##*/}")
  fi
done

if [ "$LOCAL_RUNNING" -eq 0 ] && [ "${#STOCK_PIDS[@]}" -gt 0 ]; then
  log "Closing stock Nautilus before starting Adaptive Files."

  /usr/bin/nautilus -q >/dev/null 2>&1 || true
  sleep 1

  for pid in "${STOCK_PIDS[@]}"; do
    if [ -d "/proc/$pid" ]; then
      exe="$(
        readlink -f "/proc/$pid/exe" 2>/dev/null || true
      )"

      if [ "$exe" = "/usr/bin/nautilus" ]; then
        kill "$pid" 2>/dev/null || true
      fi
    fi
  done

  sleep 1
fi

export PATH="${PREFIX}/bin:${PATH}"
export LD_LIBRARY_PATH="${PREFIX}/lib/x86_64-linux-gnu:${PREFIX}/lib:${LD_LIBRARY_PATH:-}"
export XDG_DATA_DIRS="${PREFIX}/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"

GI_REPO_DIR="$(
  find "${PREFIX}/lib" \
    -type d \
    -path '*/girepository-1.0' \
    | head -1
)"

if [ -n "$GI_REPO_DIR" ]; then
  export GI_TYPELIB_PATH="${GI_REPO_DIR}:${GI_TYPELIB_PATH:-/usr/lib/x86_64-linux-gnu/girepository-1.0}"
fi

if [ -d "${PREFIX}/share/glib-2.0/schemas" ]; then
  export GSETTINGS_SCHEMA_DIR="${PREFIX}/share/glib-2.0/schemas"
fi

unset PYTHONPATH || true
unset CMAKE_PREFIX_PATH || true
unset AMENT_PREFIX_PATH || true
unset COLCON_PREFIX_PATH || true

export GTK_THEME="AdaptiveFiles"
export ADAPTIVE_FILES_PREFIX="$PREFIX"
export ADAPTIVE_FILES_BIN="$BIN"
export ADAPTIVE_FILES_PREVIEW_CSS="$CSS"

log "Launching Adaptive Files: $BIN"

exec "$BIN" --new-window "$@"
