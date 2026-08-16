#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
PREFIX="${REPO}/.local/adaptive-nautilus"

rm -f "${PREFIX}/share/nautilus-python/extensions/adaptive_preview.py"
rm -rf "${PREFIX}/share/nautilus-python/extensions/__pycache__"
rm -f "${PREFIX}/share/adaptive-files/preview.css"

echo "Removed Adaptive Files preview extension."
echo
echo "The shared python3-nautilus package and stock Ubuntu Files were left untouched."
