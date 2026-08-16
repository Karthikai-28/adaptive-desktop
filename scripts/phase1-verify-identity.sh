#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
PREFIX="${REPO}/.local/adaptive-nautilus"
EXPECTED="${PREFIX}/bin/nautilus"

echo "===== LOCAL BINARY ====="
"$EXPECTED" --version

echo
echo "===== INSTALLED ID REFERENCES ====="
grep -RIn \
  --exclude='*.mo' \
  'com\.karthi\.AdaptiveFiles' \
  "${PREFIX}/share" \
  "${PREFIX}/bin" \
  2>/dev/null | head -60 || true

echo
echo "===== SESSION BUS NAMES ====="
if command -v busctl >/dev/null 2>&1; then
  busctl --user list 2>/dev/null \
    | grep -E 'com\.karthi\.AdaptiveFiles|org\.gnome\.Nautilus|org\.freedesktop\.FileManager1' \
    || true
else
  echo "busctl is not available."
fi

echo
echo "===== NAUTILUS PROCESSES ====="
pgrep -a nautilus || true

echo
echo "If Adaptive Files is currently open, verify its executable with:"
echo '  for p in $(pgrep -x nautilus); do echo "$p -> $(readlink -f /proc/$p/exe)"; done'
