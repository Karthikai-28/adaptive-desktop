#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
PREFIX="${REPO}/.local/adaptive-nautilus"

PACKAGE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXT_SRC="${PACKAGE_ROOT}/extension/adaptive_preview.py"
CSS_SRC="${PACKAGE_ROOT}/extension/preview.css"

if [ ! -x "${PREFIX}/bin/nautilus" ]; then
  echo "Adaptive Nautilus is not installed:"
  echo "  ${PREFIX}/bin/nautilus"
  echo
  echo "Complete the Nautilus 42.6 baseline/Phase 1 first."
  exit 1
fi

echo "Installing Nautilus 42 Python extension support..."
sudo apt update
sudo apt install -y \
  python3-nautilus \
  python3-gi \
  gir1.2-gtk-3.0 \
  poppler-utils

LOADER="$(
  dpkg -L python3-nautilus \
    | grep -E '/nautilus/extensions-3\.0/.*\.so(\.[0-9]+)*$' \
    | head -1
)"

if [ -z "$LOADER" ] || [ ! -f "$LOADER" ]; then
  echo "Could not locate libnautilus-python loader from python3-nautilus."
  echo "Run:"
  echo "  dpkg -L python3-nautilus | grep nautilus"
  exit 2
fi

LOCAL_EXT_DIR="$(
  find "${PREFIX}/lib" \
    -type d \
    -path '*/nautilus/extensions-3.0' \
    | head -1
)"

if [ -z "$LOCAL_EXT_DIR" ]; then
  LOCAL_EXT_DIR="${PREFIX}/lib/x86_64-linux-gnu/nautilus/extensions-3.0"
  mkdir -p "$LOCAL_EXT_DIR"
fi

LOCAL_PY_EXT="${PREFIX}/share/nautilus-python/extensions"
LOCAL_DATA="${PREFIX}/share/adaptive-files"

mkdir -p "$LOCAL_PY_EXT" "$LOCAL_DATA"

echo "Copying Python extension loader:"
echo "  $LOADER"
echo "  -> $LOCAL_EXT_DIR/"
cp -L "$LOADER" "$LOCAL_EXT_DIR/"

echo "Installing Adaptive Preview extension:"
cp "$EXT_SRC" "${LOCAL_PY_EXT}/adaptive_preview.py"
cp "$CSS_SRC" "${LOCAL_DATA}/preview.css"

python3 -m py_compile "${LOCAL_PY_EXT}/adaptive_preview.py"

echo
echo "Installed:"
echo "  ${LOCAL_PY_EXT}/adaptive_preview.py"
echo "  ${LOCAL_DATA}/preview.css"
echo "  ${LOCAL_EXT_DIR}/$(basename "$LOADER")"
echo
echo "Stock /usr/bin/nautilus was not modified."
echo
echo "Next:"
echo "  ./scripts/phase2.1-run-preview.sh"
