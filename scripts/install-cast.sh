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
chmod +x "$REPO/scripts/adaptive-cast-launch.sh" "$REPO/scripts/adaptive-cast-action.sh" \
    "$REPO/apps/adaptive-cast/main.py"
update-desktop-database "$APPS" 2>/dev/null || true

# Adaptive Link actions, so the phone can say "cast to the TV", "stop casting".
ACTIONS="$HOME/.config/adaptive-desktop/actions.d"
mkdir -p "$ACTIONS"
action() {
    local id="$1" title="$2" words="$3" risk="$4"; shift 4
    python3 - "$ACTIONS/$id.json" "$id" "$title" "$words" "$risk" "$REPO/scripts/adaptive-cast-action.sh" "$@" <<'PY'
import json, sys
path, ident, title, words, risk, script, *args = sys.argv[1:]
json.dump({"id": ident, "title": title, "words": words.split("|"), "risk": risk,
           "command": [script, *args]}, open(path, "w"), indent=1)
PY
}
action cast-toggle "Cast the screen to the TV, or stop" "cast|cast to tv|screen to tv|mirror to tv|tv" changes --toggle
action cast-stop "Stop casting to the TV" "stop casting|stop cast|stop tv" safe --stop
action cast-freeze "Freeze the TV picture" "freeze tv|pause tv|hold the tv" safe --freeze
action cast-curtain "Curtain on the TV" "curtain|hide tv|be right back" safe --curtain
action cast-resume "Show the screen on the TV again" "resume tv|unfreeze|lift curtain" safe --resume
action cast-wall "Show the wall on the TV" "wall|tv clock|tv dashboard" changes --wall

echo "Installed:"
echo "  $APPS/$DESKTOP"
missing="$(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import session; print(" ".join(session.missing_elements()))' "$REPO/apps/adaptive-cast" 2>/dev/null || true)"
if [ -n "$missing" ]; then
    echo "Before casting, install: sudo apt install $missing"
fi
