#!/usr/bin/env bash
# Install and start the fifteen-minute home index for the Command palette
# (systemd user timer). Undo with: systemctl --user disable --now adaptive-index.timer
set -Eeuo pipefail
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/adaptive-paths.sh"
REPO="$ADAPTIVE_REPO"
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"
adaptive_render "$REPO/services/adaptive-index.service" "$UNIT_DIR/adaptive-index.service"
adaptive_render "$REPO/services/adaptive-index.timer" "$UNIT_DIR/adaptive-index.timer"
systemctl --user daemon-reload
systemctl --user enable --now adaptive-index.timer
"$REPO/scripts/adaptive-index.sh"   # build one now
"$REPO/scripts/adaptive-index.sh" --status
