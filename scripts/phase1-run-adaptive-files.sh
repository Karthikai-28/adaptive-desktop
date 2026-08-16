#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
PREFIX="${REPO}/.local/adaptive-nautilus"
BIN="${PREFIX}/bin/nautilus"

if [ ! -x "$BIN" ]; then
  echo "Missing local binary:"
  echo "  $BIN"
  exit 1
fi

export PATH="${PREFIX}/bin:${PATH}"
export LD_LIBRARY_PATH="${PREFIX}/lib/x86_64-linux-gnu:${PREFIX}/lib:${LD_LIBRARY_PATH:-}"
export XDG_DATA_DIRS="${PREFIX}/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"

if [ -d "${PREFIX}/share/glib-2.0/schemas" ]; then
  export GSETTINGS_SCHEMA_DIR="${PREFIX}/share/glib-2.0/schemas"
fi

exec "$BIN" --new-window "$@"
