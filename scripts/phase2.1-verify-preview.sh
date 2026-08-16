#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
PREFIX="${REPO}/.local/adaptive-nautilus"

echo "===== ADAPTIVE FILES ====="
"${PREFIX}/bin/nautilus" --version

echo
echo "===== EXTENSION SCRIPT ====="
test -f "${PREFIX}/share/nautilus-python/extensions/adaptive_preview.py"
python3 -m py_compile "${PREFIX}/share/nautilus-python/extensions/adaptive_preview.py"
echo "PASS"

echo
echo "===== PYTHON LOADER ====="
find "${PREFIX}/lib" \
  -path '*/nautilus/extensions-3.0/*' \
  -type f \
  -o -type l \
  | grep -E 'libnautilus-python|python' \
  || true

echo
echo "===== NAUTILUS 3 TYPELIB ====="
find "${PREFIX}/lib" \
  -path '*/girepository-1.0/Nautilus-3.0.typelib' \
  -print

echo
echo "===== RUNNING PROCESS ====="
pgrep -a nautilus || true

PID="$(pgrep -n -x nautilus || true)"

if [ -n "$PID" ]; then
  echo
  echo "Executable:"
  readlink -f "/proc/$PID/exe"

  echo
  echo "Loaded python extension module:"
  grep -E 'libnautilus-python|nautilus-python' "/proc/$PID/maps" 2>/dev/null \
    | head -10 \
    || true

  echo
  echo "Adaptive environment:"
  tr '\0' '\n' < "/proc/$PID/environ" \
    | grep -E '^(GTK_THEME|ADAPTIVE_FILES_|GI_TYPELIB_PATH|XDG_DATA_DIRS)=' \
    || true
fi

echo
echo "===== EXTENSION LOG ====="
tail -80 "${HOME}/.cache/adaptive-files/preview-extension.log" 2>/dev/null || true
