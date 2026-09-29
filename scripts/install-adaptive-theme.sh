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
# Covers four surfaces: the GTK theme, the icon theme, the desktop background,
# and the interface fonts. The last two were the remaining stock-Ubuntu
# giveaways in an otherwise Adaptive session - warty-final-ubuntu.png and the
# Ubuntu type family.
#

REPO="${HOME}/adaptive-desktop"
THEME_SRC="${REPO}/theme/Adaptive"
ICONS_SRC="${REPO}/icons/AdaptiveFilesIcons"
THEME_DST="${HOME}/.local/share/themes/Adaptive"
ICONS_DST="${HOME}/.local/share/icons/AdaptiveFilesIcons"
BG_SRC="${REPO}/design/backgrounds"
BG_DST="${HOME}/.local/share/backgrounds"

# Inter is the shell's type (panel, dock, Shade, Control Center), so the
# session font is Inter too: one typeface across shell chrome and every GTK
# window is most of what "the same skin" means once the palette matches.
# 10.5pt keeps GTK text the size Cantarell 11 was; Inter runs wider.
# Cantarell stays installed as the fallback if Inter is unavailable.
UI_FONT="Inter 10.5"
DOC_FONT="Inter 11"
MONO_FONT="JetBrainsMono Nerd Font 12"

# Inter is installed per-user from Ubuntu's own package rather than with apt,
# so this script still needs no root; `rm -rf ~/.local/share/fonts/inter`
# undoes it.
install_inter() {
    local dst="${HOME}/.local/share/fonts/inter"

    if fc-list : family | tr ',' '\n' | grep -qx "Inter"; then
        echo "  Inter already installed"
        return 0
    fi

    local tmp
    tmp="$(mktemp -d)"
    if (cd "$tmp" && apt-get download fonts-inter >/dev/null 2>&1); then
        dpkg-deb -x "$tmp"/fonts-inter_*.deb "$tmp/x" 2>/dev/null || true
        if compgen -G "$tmp/x/usr/share/fonts/**/*.otf" >/dev/null 2>&1 ||
           find "$tmp/x" -name '*.otf' -print -quit | grep -q .; then
            mkdir -p "$dst"
            find "$tmp/x" -name '*.otf' -exec cp {} "$dst/" \;
            fc-cache -f "${HOME}/.local/share/fonts" >/dev/null 2>&1
            echo "  $dst ($(find "$dst" -name '*.otf' | wc -l) faces)"
        fi
    else
        # Not fatal: the shade's font stack falls back to Cantarell, so the
        # only loss is a little crispness at small sizes.
        echo "  Inter unavailable (offline?); falling back to Cantarell"
        UI_FONT="Cantarell 11"
        DOC_FONT="Cantarell 11"
    fi
    rm -rf "$tmp"
}

echo "Installing Inter, the Adaptive UI typeface..."
install_inter

echo "Building theme from tokens..."
"${REPO}/scripts/build-adaptive-theme.py"

echo "Building backgrounds from tokens..."
"${REPO}/scripts/build-adaptive-backgrounds.py"

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

mkdir -p "$BG_DST"
rsync -a "${BG_SRC}/" "${BG_DST}/"
echo "  $BG_DST"

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -f "$ICONS_DST" 2>/dev/null || true
fi

echo
if [ "${DCONF_PROFILE:-}" = "adaptive" ]; then
    gsettings set org.gnome.desktop.interface gtk-theme 'Adaptive'
    gsettings set org.gnome.desktop.interface icon-theme 'AdaptiveFilesIcons'
    gsettings set org.gnome.desktop.interface color-scheme 'prefer-dark'

    gsettings set org.gnome.desktop.interface font-name "$UI_FONT"
    gsettings set org.gnome.desktop.interface document-font-name "$DOC_FONT"
    gsettings set org.gnome.desktop.interface monospace-font-name "$MONO_FONT"

    # picture-uri and picture-uri-dark both, or the background reverts the
    # moment color-scheme flips. primary-color is what shows during the gap
    # before the file loads, so it gets the same canvas value.
    BG_URI="file://${BG_DST}/adaptive-desktop.png"
    gsettings set org.gnome.desktop.background picture-uri "$BG_URI"
    gsettings set org.gnome.desktop.background picture-uri-dark "$BG_URI"
    gsettings set org.gnome.desktop.background picture-options 'zoom'
    gsettings set org.gnome.desktop.background primary-color "$(
        python3 -c "import json,sys; print(json.load(open('${REPO}/tokens/adaptive.tokens.json'))['color']['bg.canvas'])"
    )"

    # The lock shield already has its own image; point the screensaver key at
    # it so the blanked-screen colour matches instead of falling back to grey.
    gsettings set org.gnome.desktop.screensaver picture-uri "file://${BG_DST}/adaptive-lock.png"
    gsettings set org.gnome.desktop.screensaver picture-options 'zoom'

    echo "Adaptive session appearance set:"
    echo "  gtk-theme    $(gsettings get org.gnome.desktop.interface gtk-theme)"
    echo "  icon-theme   $(gsettings get org.gnome.desktop.interface icon-theme)"
    echo "  font         $(gsettings get org.gnome.desktop.interface font-name)"
    echo "  monospace    $(gsettings get org.gnome.desktop.interface monospace-font-name)"
    echo "  background   $(gsettings get org.gnome.desktop.background picture-uri)"
else
    echo "Not inside the Adaptive dconf profile (DCONF_PROFILE='${DCONF_PROFILE:-}')."
    echo "Files were installed, but no session settings were changed."
    echo "Run this again from inside Adaptive Desktop to apply the appearance."
fi

echo
echo "Normal Ubuntu keeps Yaru."
