#!/usr/bin/env bash
# Install and start the fifteen-minute home index for the Command palette
# (systemd user timer). Undo with: systemctl --user disable --now adaptive-index.timer
set -Eeuo pipefail
REPO="${ADAPTIVE_REPO:-$HOME/adaptive-desktop}"
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"
install -m 0644 "$REPO/services/adaptive-index.service" "$UNIT_DIR/"
install -m 0644 "$REPO/services/adaptive-index.timer" "$UNIT_DIR/"
systemctl --user daemon-reload
systemctl --user enable --now adaptive-index.timer
"$REPO/scripts/adaptive-index.sh"   # build one now
"$REPO/scripts/adaptive-index.sh" --status
