#!/usr/bin/env bash
# Install and start the hourly wallpaper rotation (systemd user timer).
set -Eeuo pipefail
REPO="${ADAPTIVE_REPO:-$HOME/adaptive-desktop}"
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"
install -m 0644 "$REPO/services/adaptive-wallpaper.service" "$UNIT_DIR/"
install -m 0644 "$REPO/services/adaptive-wallpaper.timer" "$UNIT_DIR/"
systemctl --user daemon-reload
systemctl --user enable --now adaptive-wallpaper.timer
"$REPO/scripts/adaptive-wallpaper.sh"   # set one now
echo
echo "Rotation active. Next changes hourly. Status:"
systemctl --user status adaptive-wallpaper.timer --no-pager | head -5 || true
