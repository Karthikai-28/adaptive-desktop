#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
PREFIX="${REPO}/.local/adaptive-nautilus"
PACKAGE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ ! -x "${PREFIX}/bin/nautilus" ]; then
  echo "Adaptive Nautilus is not installed:"
  echo "  ${PREFIX}/bin/nautilus"
  exit 1
fi

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
  echo "Could not locate the nautilus-python loader."
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

mkdir -p \
  "${PREFIX}/share/themes" \
  "${PREFIX}/share/icons" \
  "${PREFIX}/share/nautilus-python/extensions" \
  "${PREFIX}/share/adaptive-files" \
  "${REPO}/backups"

STAMP="$(date +%Y%m%d-%H%M%S)"

for path in \
  "${PREFIX}/share/themes/AdaptiveFiles" \
  "${PREFIX}/share/icons/AdaptiveFilesIcons" \
  "${PREFIX}/share/nautilus-python/extensions/adaptive_preview.py" \
  "${PREFIX}/share/adaptive-files/preview.css"
do
  if [ -e "$path" ]; then
    rel="${path#${PREFIX}/}"
    dst="${REPO}/backups/visual-preview-v1.1-${STAMP}/${rel}"
    mkdir -p "$(dirname "$dst")"
    cp -a "$path" "$dst"
  fi
done

rm -rf \
  "${PREFIX}/share/themes/AdaptiveFiles" \
  "${PREFIX}/share/icons/AdaptiveFilesIcons"

cp -a \
  "${PACKAGE_ROOT}/theme/AdaptiveFiles" \
  "${PREFIX}/share/themes/AdaptiveFiles"

cp -a \
  "${PACKAGE_ROOT}/icons/AdaptiveFilesIcons" \
  "${PREFIX}/share/icons/AdaptiveFilesIcons"

cp -L "$LOADER" "$LOCAL_EXT_DIR/"
cp \
  "${PACKAGE_ROOT}/extension/adaptive_preview.py" \
  "${PREFIX}/share/nautilus-python/extensions/adaptive_preview.py"
cp \
  "${PACKAGE_ROOT}/extension/preview.css" \
  "${PREFIX}/share/adaptive-files/preview.css"

python3 -m py_compile \
  "${PREFIX}/share/nautilus-python/extensions/adaptive_preview.py"

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache \
    -f \
    "${PREFIX}/share/icons/AdaptiveFilesIcons" \
    >/dev/null 2>&1 || true
fi

echo
echo "Adaptive Files v1.3 visual + preview layer installed."
echo
echo "Important: close all existing Nautilus processes before launch:"
echo "  /usr/bin/nautilus -q || true"
echo "  pkill -x nautilus || true"
echo "  sleep 2"
echo
echo "Then:"
echo "  ./scripts/phase2.4-run-visual-preview.sh"
