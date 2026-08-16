#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
PREFIX="${REPO}/.local/adaptive-nautilus"
THEME_DST="${PREFIX}/share/themes/AdaptiveFiles"
PACKAGE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
THEME_SRC="${PACKAGE_ROOT}/theme/AdaptiveFiles"

if [ ! -x "${PREFIX}/bin/nautilus" ]; then
  echo "Adaptive Nautilus binary not found:"
  echo "  ${PREFIX}/bin/nautilus"
  echo
  echo "Complete Phase 1 first."
  exit 1
fi

if [ ! -d "$THEME_SRC" ]; then
  echo "Theme source not found:"
  echo "  $THEME_SRC"
  exit 1
fi

if [ -d "$THEME_DST" ]; then
  BACKUP="${REPO}/backups/AdaptiveFiles-theme-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$(dirname "$BACKUP")"
  cp -a "$THEME_DST" "$BACKUP"
  echo "Backed up existing visual layer to:"
  echo "  $BACKUP"
fi

rm -rf "$THEME_DST"
mkdir -p "$(dirname "$THEME_DST")"
cp -a "$THEME_SRC" "$THEME_DST"

echo
echo "Installed process-local visual layer:"
echo "  $THEME_DST"
echo
echo "Stock Ubuntu theme was not changed."
echo
echo "Launch with:"
echo "  ./scripts/phase2-run-visual.sh"
