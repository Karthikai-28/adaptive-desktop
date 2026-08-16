#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
PREFIX="${REPO}/.local/adaptive-nautilus"
BIN="${PREFIX}/bin/nautilus"
CSS="${PREFIX}/share/adaptive-files/preview.css"

if [ ! -x "$BIN" ]; then
  echo "Missing Adaptive Files binary:"
  echo "  $BIN"
  exit 1
fi

if [ ! -f "${PREFIX}/share/nautilus-python/extensions/adaptive_preview.py" ]; then
  echo "Preview extension is not installed."
  echo "Run:"
  echo "  ./scripts/phase2.1-install-preview.sh"
  exit 1
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

# Keep ROS/user Python overlays out of the embedded extension runtime.
unset PYTHONPATH || true

export GTK_THEME="AdaptiveFiles"
export ADAPTIVE_FILES_PREFIX="$PREFIX"
export ADAPTIVE_FILES_BIN="$BIN"
export ADAPTIVE_FILES_PREVIEW_CSS="$CSS"

mkdir -p "${HOME}/.cache/adaptive-files"
: > "${HOME}/.cache/adaptive-files/preview-extension.log"

exec "$BIN" --new-window "$@"
