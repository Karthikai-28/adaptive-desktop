#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
PREFIX="${REPO}/.local/adaptive-nautilus"
CSS="${PREFIX}/share/themes/AdaptiveFiles/gtk-3.0/gtk.css"

echo "===== BINARY ====="
"${PREFIX}/bin/nautilus" --version

echo
echo "===== VISUAL LAYER ====="
if [ -f "$CSS" ]; then
  echo "PASS: $CSS"
else
  echo "FAIL: $CSS is missing"
  exit 2
fi

echo
echo "===== THEME TOKENS ====="
grep -E '^@define-color af_(bg|surface|accent|cyan|text)' "$CSS" || true

echo
echo "===== PROCESS CHECK ====="
pgrep -a nautilus || true

echo
echo "When launched with phase2-run-visual.sh, the process receives:"
echo "  GTK_THEME=AdaptiveFiles"
