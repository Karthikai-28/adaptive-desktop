#!/usr/bin/env bash
# Summon or dismiss Home (Super+H), as fast as a key should be.
#
#   adaptive-home.sh              show Home, or hide it if it is showing
#   adaptive-home.sh show [TAB]   show it, on Today or on a tab (mail, calendar, ...)
#   adaptive-home.sh hide
#
# Home is already running, loaded and hidden (apps/mario-home/host.py --background at login), so
# this only sends it a message over the session bus. If it is not running, it is started.
set -Eeuo pipefail

. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/adaptive-paths.sh"
HOST="$ADAPTIVE_REPO/apps/mario-home/host.py"

act() {  # act <action> [<gvariant parameter>]
    gdbus call --session --dest com.karthi.MarioHome --object-path /com/karthi/MarioHome \
        --method org.gtk.Actions.Activate "$1" "[${2:-}]" '{}' >/dev/null 2>&1
}

case "${1:-toggle}" in
    toggle) act toggle || exec /usr/bin/python3 "$HOST" --show ;;
    show)   act show "<'${2:-}'>" || exec /usr/bin/python3 "$HOST" --show ${2:+"$2"} ;;
    hide)   act hide || true ;;
    *) echo "usage: adaptive-home.sh [toggle | show [TAB] | hide]" >&2; exit 2 ;;
esac
