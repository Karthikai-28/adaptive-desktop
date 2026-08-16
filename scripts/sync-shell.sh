#!/usr/bin/env bash
set -Eeuo pipefail

UUID="adaptive-shell@local"

SOURCE="$HOME/adaptive-desktop/shell/$UUID"
TARGET="$HOME/.local/share/gnome-shell/extensions/$UUID"

mkdir -p "$TARGET"

rsync -a --delete \
    "$SOURCE/" \
    "$TARGET/"

echo "Adaptive Shell synced:"
echo "$SOURCE"
echo " -> "
echo "$TARGET"
