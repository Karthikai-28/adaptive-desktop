#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"

echo "STEP 2 — NATIVE PREVIEW STACK"
echo

"${REPO}/scripts/phase2.5-verify-native-preview.sh"

echo
echo "Check above for:"
echo "  Native GNOME thumbnail factory initialized."
echo "  Native thumbnail cache hit/generated for PDF or image."
echo "  GtkSourceView language: ... for source files."
