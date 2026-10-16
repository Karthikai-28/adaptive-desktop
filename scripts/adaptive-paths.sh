# Where this checkout of Adaptive Desktop is, for every script in it.
#
# Source it from a script in scripts/ (or with a path from anywhere):
#
#     . "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/adaptive-paths.sh"
#
# and use $ADAPTIVE_REPO. The repository can be cloned anywhere, by any user:
# nothing assumes ~/adaptive-desktop or a user name. The order is
#
#   1. ADAPTIVE_REPO from the environment, when set
#   2. the folder this file is in, one level up - the checkout itself
#
# Files installed outside the checkout (systemd units, autostart and app-grid
# entries) are templates with @ADAPTIVE_REPO@ in them; adaptive_render fills
# it in as they are installed. Things that cannot see the checkout at all -
# the login session wrapper and the shell extension's live copy - read the
# path adaptive_record_repo leaves in ~/.config/adaptive-desktop/repo.
#
# shellcheck shell=bash

ADAPTIVE_REPO="${ADAPTIVE_REPO:-$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)}"
ADAPTIVE_LOCATOR="${XDG_CONFIG_HOME:-$HOME/.config}/adaptive-desktop/repo"
export ADAPTIVE_REPO

# adaptive_render TEMPLATE DESTINATION [MODE]: install a template with the
# checkout's path in place of @ADAPTIVE_REPO@.
adaptive_render() {
    local source="$1" target="$2" mode="${3:-0644}"
    mkdir -p "$(dirname "$target")"
    sed "s|@ADAPTIVE_REPO@|$ADAPTIVE_REPO|g" "$source" > "$target.tmp"
    chmod "$mode" "$target.tmp"
    mv -f "$target.tmp" "$target"
}

# Leave the checkout's path where the session wrapper and the shell find it.
adaptive_record_repo() {
    mkdir -p "$(dirname "$ADAPTIVE_LOCATOR")"
    printf '%s\n' "$ADAPTIVE_REPO" > "$ADAPTIVE_LOCATOR"
}
