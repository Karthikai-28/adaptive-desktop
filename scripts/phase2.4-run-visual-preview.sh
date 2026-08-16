#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
PREFIX="${REPO}/.local/adaptive-nautilus"
BIN="${PREFIX}/bin/nautilus"
CSS="${PREFIX}/share/adaptive-files/preview.css"

if [ ! -x "$BIN" ]; then
  echo "Missing local Adaptive Nautilus binary:"
  echo "  $BIN"
  exit 1
fi

# Fail instead of silently handing activation to an already running stock
# Files. Do not use pgrep -x here: a GApplication build may expose a comm name
# different from the executable basename.
for proc in /proc/[0-9]*; do
  [ -e "$proc/exe" ] || continue
  exe="$(readlink -f "$proc/exe" 2>/dev/null || true)"

  case "$exe" in
    /usr/bin/nautilus|/usr/libexec/nautilus*)
      echo "Stock/system Nautilus is already running:"
      echo "  PID ${proc##*/} -> $exe"
      echo
      echo "Close it first:"
      echo "  /usr/bin/nautilus -q || true"
      echo "  pkill -x nautilus || true"
      echo "  sleep 2"
      exit 3
      ;;
  esac
done

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

mkdir -p "${HOME}/.cache/adaptive-files"
: > "${HOME}/.cache/adaptive-files/preview-extension.log"

echo "Launching:"
echo "  $BIN"
echo
echo "Expected UI:"
echo "  - ADAPTIVE FILES / Inspector / Storage / Network strip"
echo "  - permanent right inspector"
echo "  - custom blue/cyan SVG icons"
echo
echo "Keep this terminal open for runtime warnings."
echo

exec "$BIN" --new-window "$@"
