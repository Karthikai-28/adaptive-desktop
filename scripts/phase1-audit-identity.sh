#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
SOURCE_FILE="${REPO}/vendor/NAUTILUS_SOURCE_PATH"
OUT="${REPO}/nautilus-identity-audit.txt"

if [ ! -f "$SOURCE_FILE" ]; then
  echo "Missing: $SOURCE_FILE"
  exit 1
fi

SOURCE="$(cat "$SOURCE_FILE")"

if [ ! -d "$SOURCE" ]; then
  echo "Source directory does not exist: $SOURCE"
  exit 1
fi

{
  echo "===== SOURCE ====="
  echo "$SOURCE"

  echo
  echo "===== APPLICATION / DBUS IDENTIFIERS ====="
  grep -RInE \
    --exclude-dir=.git \
    --exclude-dir=po \
    --exclude='*.mo' \
    'org\.gnome\.Nautilus|org\.freedesktop\.FileManager1|application[-_]id|APPLICATION_ID|DBusActivatable|search-provider' \
    "$SOURCE/src" \
    "$SOURCE/data" \
    "$SOURCE/meson.build" \
    "$SOURCE/meson_options.txt" \
    2>/dev/null || true

  echo
  echo "===== MESON ID DEFINITIONS ====="
  grep -nE \
    'application[_-]id|org\.gnome\.Nautilus' \
    "$SOURCE/meson.build" \
    "$SOURCE/data/meson.build" \
    2>/dev/null || true

  echo
  echo "===== DESKTOP / SERVICE / SEARCH FILES ====="
  find "$SOURCE/data" \
    -maxdepth 3 \
    -type f \
    \( \
      -name '*.desktop*' \
      -o -name '*.service*' \
      -o -name '*search-provider*' \
      -o -name '*.gschema.xml*' \
    \) \
    -print | sort
} | tee "$OUT"

echo
echo "Audit written to:"
echo "  $OUT"
