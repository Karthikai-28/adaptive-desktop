#!/usr/bin/env bash
# Install and start the hourly wallpaper rotation (systemd user timer).
set -Eeuo pipefail
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/adaptive-paths.sh"
REPO="$ADAPTIVE_REPO"
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"
adaptive_render "$REPO/services/adaptive-wallpaper.service" "$UNIT_DIR/adaptive-wallpaper.service"
adaptive_render "$REPO/services/adaptive-wallpaper.timer" "$UNIT_DIR/adaptive-wallpaper.timer"
systemctl --user daemon-reload
systemctl --user enable --now adaptive-wallpaper.timer
"$REPO/scripts/adaptive-wallpaper.sh"   # set one now
echo
echo "Rotation active. Next changes hourly. Status:"
systemctl --user status adaptive-wallpaper.timer --no-pager | head -5 || true
