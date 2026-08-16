#!/usr/bin/env bash
set -Eeuo pipefail

#
# Installs the Adaptive visual system for this user and points the Adaptive
# session at it.
#
# Everything lands in XDG_DATA_HOME, which GTK always searches, so the skin
# does not depend on the session wrapper's XDG_DATA_DIRS being reinstalled.
#
# The gsettings writes are guarded on the Adaptive dconf profile: theming the
# normal Ubuntu session is out of scope and would break the recovery path's
# familiar appearance.
#

REPO="${HOME}/adaptive-desktop"
THEME_SRC="${REPO}/theme/Adaptive"
ICONS_SRC="${REPO}/icons/AdaptiveFilesIcons"
THEME_DST="${HOME}/.local/share/themes/Adaptive"
ICONS_DST="${HOME}/.local/share/icons/AdaptiveFilesIcons"

echo "Building theme from tokens..."
"${REPO}/scripts/build-adaptive-theme.py"

echo
echo "Installing:"

mkdir -p "$(dirname "$THEME_DST")" "$(dirname "$ICONS_DST")"
rsync -a --delete "${THEME_SRC}/" "${THEME_DST}/"
echo "  $THEME_DST"

rsync -a --delete "${ICONS_SRC}/" "${ICONS_DST}/"
echo "  $ICONS_DST"

# Nautilus reads its icons from the fork prefix too, so keep that copy in step.
FORK_ICONS="${REPO}/.local/adaptive-nautilus/share/icons/AdaptiveFilesIcons"
if [ -d "$FORK_ICONS" ]; then
    rsync -a --delete "${ICONS_SRC}/" "${FORK_ICONS}/"
    echo "  $FORK_ICONS"
fi

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -f "$ICONS_DST" 2>/dev/null || true
fi

echo
if [ "${DCONF_PROFILE:-}" = "adaptive" ]; then
    gsettings set org.gnome.desktop.interface gtk-theme 'Adaptive'
    gsettings set org.gnome.desktop.interface icon-theme 'AdaptiveFilesIcons'
    gsettings set org.gnome.desktop.interface color-scheme 'prefer-dark'

    echo "Adaptive session appearance set:"
    echo "  gtk-theme    $(gsettings get org.gnome.desktop.interface gtk-theme)"
    echo "  icon-theme   $(gsettings get org.gnome.desktop.interface icon-theme)"
else
    echo "Not inside the Adaptive dconf profile (DCONF_PROFILE='${DCONF_PROFILE:-}')."
    echo "Files were installed, but no session settings were changed."
    echo "Run this again from inside Adaptive Desktop to apply the appearance."
fi

echo
echo "Normal Ubuntu keeps Yaru."
