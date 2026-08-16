#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
LIVE="${HOME}/.local/share/gnome-shell/extensions/adaptive-shell@local"

echo "STEP 3 — DOCK + APP LAUNCHERS"
echo

test -f "${LIVE}/extension.js"
echo "PASS: live Adaptive Shell extension.js"

test -f "${LIVE}/assets/dock/files.svg"
echo "PASS: custom Files dock SVG"

"${REPO}/scripts/verify-adaptive-files-stack.sh"

command -v gnome-control-center >/dev/null
echo "PASS: Settings launcher target exists"

echo
echo "Extension state:"
gnome-extensions info adaptive-shell@local | sed -n '1,30p'

echo
echo "Manual click verification:"
echo "  1. Overview button opens GNOME overview."
echo "  2. Files button opens Adaptive Files."
echo "  3. Apps button opens the application grid."
echo "  4. Workspaces button opens workspace overview."
echo "  5. Search button opens GNOME overview/search surface."
echo "  6. Bottom Settings button opens Settings."
