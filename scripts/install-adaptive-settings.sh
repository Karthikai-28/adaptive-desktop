#!/usr/bin/env bash
set -Eeuo pipefail

# Install the Adaptive Settings app for this user. It holds the sections
# gnome-control-center has no panel for: Projects & Workspaces, Search &
# Commands, and Updates & Recovery.
#
#   app       apps/adaptive-settings   ("Adaptive Settings")
#   launcher  scripts/adaptive-settings-launch.sh [--section projects|search|system]

. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/adaptive-paths.sh"
REPO="$ADAPTIVE_REPO"
APPS="$HOME/.local/share/applications"
DESKTOP="com.karthi.AdaptiveSettings.desktop"

mkdir -p "$APPS"
adaptive_render "$REPO/apps/adaptive-settings/$DESKTOP" "$APPS/$DESKTOP"
chmod +x "$REPO/scripts/adaptive-settings-launch.sh" "$REPO/apps/adaptive-settings/main.py"
update-desktop-database "$APPS" 2>/dev/null || true

echo "Installed:"
echo "  $APPS/$DESKTOP"
echo "Open it from the app grid, the Command palette, or:"
echo "  $REPO/scripts/adaptive-settings-launch.sh --section projects"
