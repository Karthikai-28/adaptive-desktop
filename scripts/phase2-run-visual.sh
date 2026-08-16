#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
PREFIX="${REPO}/.local/adaptive-nautilus"
BIN="${PREFIX}/bin/nautilus"

if [ ! -x "$BIN" ]; then
  echo "Missing Adaptive Files binary:"
  echo "  $BIN"
  exit 1
fi

if [ ! -f "${PREFIX}/share/themes/AdaptiveFiles/gtk-3.0/gtk.css" ]; then
  echo "AdaptiveFiles visual layer is not installed."
  echo "Run:"
  echo "  ./scripts/phase2-install-visual-layer.sh"
  exit 1
fi

# Keep the fork's libraries/resources first.
export PATH="${PREFIX}/bin:${PATH}"
export LD_LIBRARY_PATH="${PREFIX}/lib/x86_64-linux-gnu:${PREFIX}/lib:${LD_LIBRARY_PATH:-}"
export XDG_DATA_DIRS="${PREFIX}/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"

if [ -d "${PREFIX}/share/glib-2.0/schemas" ]; then
  export GSETTINGS_SCHEMA_DIR="${PREFIX}/share/glib-2.0/schemas"
fi

# Critical: process-local. This does not retheme the rest of the Ubuntu session.
export GTK_THEME="AdaptiveFiles"

exec "$BIN" --new-window "$@"
