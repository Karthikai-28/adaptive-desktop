#!/usr/bin/env bash
set -Eeuo pipefail

# Install the Adaptive Settings app for this user. It holds the sections
# gnome-control-center has no panel for: Projects & Workspaces, Search &
# Commands, and Updates & Recovery.
#
#   app       apps/adaptive-settings   ("Adaptive Settings")
#   launcher  scripts/adaptive-settings-launch.sh [--section projects|search|system]

REPO="${ADAPTIVE_REPO:-$HOME/adaptive-desktop}"
APPS="$HOME/.local/share/applications"
DESKTOP="com.karthi.AdaptiveSettings.desktop"

mkdir -p "$APPS"
sed "s|/home/karthi/adaptive-desktop|$REPO|g" \
    "$REPO/apps/adaptive-settings/$DESKTOP" > "$APPS/$DESKTOP"
chmod 0644 "$APPS/$DESKTOP"
chmod +x "$REPO/scripts/adaptive-settings-launch.sh" "$REPO/apps/adaptive-settings/main.py"
update-desktop-database "$APPS" 2>/dev/null || true

echo "Installed:"
echo "  $APPS/$DESKTOP"
echo "Open it from the app grid, the Command palette, or:"
echo "  $REPO/scripts/adaptive-settings-launch.sh --section projects"
