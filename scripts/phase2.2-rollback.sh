#!/usr/bin/env bash
set -Eeuo pipefail

PREFIX="${HOME}/adaptive-desktop/.local/adaptive-nautilus"

rm -rf \
  "${PREFIX}/share/themes/AdaptiveFiles" \
  "${PREFIX}/share/icons/AdaptiveFilesIcons"

rm -f \
  "${PREFIX}/share/nautilus-python/extensions/adaptive_preview.py" \
  "${PREFIX}/share/adaptive-files/preview.css"

rm -rf \
  "${PREFIX}/share/nautilus-python/extensions/__pycache__"

echo "Removed v1.1 visual/preview layer from the local fork."
echo "Stock Ubuntu Files was not modified."
