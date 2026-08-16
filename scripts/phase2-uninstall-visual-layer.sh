#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
PREFIX="${REPO}/.local/adaptive-nautilus"
THEME="${PREFIX}/share/themes/AdaptiveFiles"

if [ -d "$THEME" ]; then
  rm -rf "$THEME"
  echo "Removed:"
  echo "  $THEME"
else
  echo "Nothing to remove."
fi

echo
echo "Stock Ubuntu Files/theme was never modified."
