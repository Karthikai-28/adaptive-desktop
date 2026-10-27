#!/usr/bin/env bash
set -Eeuo pipefail

# Install Cast, the wireless display app (Miracast over Wi-Fi Direct).
#
#   app       apps/adaptive-cast   ("Cast")
#   launcher  scripts/adaptive-cast-launch.sh [--list | --connect NAME]
#
# It needs an H.264 encoder and the MPEG-TS muxer, which are system packages;
# this only says so, since installing them needs sudo.

. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/adaptive-paths.sh"
REPO="$ADAPTIVE_REPO"
APPS="$HOME/.local/share/applications"
DESKTOP="com.karthi.AdaptiveCast.desktop"

mkdir -p "$APPS"
adaptive_render "$REPO/apps/adaptive-cast/$DESKTOP" "$APPS/$DESKTOP"
chmod +x "$REPO/scripts/adaptive-cast-launch.sh" "$REPO/apps/adaptive-cast/main.py"
update-desktop-database "$APPS" 2>/dev/null || true

echo "Installed:"
echo "  $APPS/$DESKTOP"
missing="$(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import session; print(" ".join(session.missing_elements()))' "$REPO/apps/adaptive-cast" 2>/dev/null || true)"
if [ -n "$missing" ]; then
    echo "Before casting, install: sudo apt install $missing"
fi
