#!/usr/bin/env bash
# Rotate the Adaptive desktop and lock-screen wallpaper.
#
# Cycles through the astrophotography set in design/backgrounds/astro (kept in
# the repo), one image per run, remembering its place in a state file. The
# systemd user timer adaptive-wallpaper.timer runs it hourly; run it by hand
# to advance now, or with --set <file> to pin one image.
#
# Both the desktop and the lock screen are set, under the Adaptive dconf
# profile only, so the normal Ubuntu session is untouched.
set -Eeuo pipefail

REPO="${ADAPTIVE_REPO:-$HOME/adaptive-desktop}"
DIR="$REPO/design/backgrounds/astro"
STATE_DIR="$HOME/.local/state/adaptive-desktop"
INDEX_FILE="$STATE_DIR/wallpaper-index"
mkdir -p "$STATE_DIR"

export DCONF_PROFILE=adaptive
# A user timer may start before the session bus is in its environment.
[ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ] || \
    export DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus"

mapfile -t IMAGES < <(find "$DIR" -maxdepth 1 -type f \
    \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' \) | sort)
if [ "${#IMAGES[@]}" -eq 0 ]; then
    echo "No wallpapers in $DIR" >&2
    exit 1
fi

if [ "${1:-}" = "--set" ] && [ -n "${2:-}" ]; then
    PICK="$2"
else
    prev=-1
    [ -f "$INDEX_FILE" ] && prev=$(cat "$INDEX_FILE" 2>/dev/null || echo -1)
    case "$prev" in ''|*[!0-9-]*) prev=-1 ;; esac
    idx=$(( (prev + 1) % ${#IMAGES[@]} ))
    PICK="${IMAGES[$idx]}"
    echo "$idx" > "$INDEX_FILE"
fi

URI="file://$PICK"
gsettings set org.gnome.desktop.background picture-uri "$URI"
gsettings set org.gnome.desktop.background picture-uri-dark "$URI"
gsettings set org.gnome.desktop.background picture-options 'zoom'
gsettings set org.gnome.desktop.background primary-color '#141416'
gsettings set org.gnome.desktop.screensaver picture-uri "$URI"
gsettings set org.gnome.desktop.screensaver picture-options 'zoom'

echo "Wallpaper set: $(basename "$PICK")"
