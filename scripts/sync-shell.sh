#!/usr/bin/env bash
set -Eeuo pipefail

UUID="adaptive-shell@local"

. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/adaptive-paths.sh"
SOURCE="$ADAPTIVE_REPO/shell/$UUID"
# The live copy cannot see where it came from; the shell reads this.
adaptive_record_repo
TARGET="$HOME/.local/share/gnome-shell/extensions/$UUID"

mkdir -p "$TARGET"

rsync -a --delete \
    "$SOURCE/" \
    "$TARGET/"

echo "Adaptive Shell synced:"
echo "$SOURCE"
echo " -> "
echo "$TARGET"
