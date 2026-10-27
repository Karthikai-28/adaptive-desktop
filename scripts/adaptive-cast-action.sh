#!/usr/bin/env bash
# A Cast command that returns at once: for callers that wait for the command
# to finish (Adaptive Link actions, the shell). Cast itself keeps running for
# as long as it casts, so it is started detached and its output dropped.
#
#   adaptive-cast-action.sh --toggle | --stop | --freeze | --curtain | --resume | --wall | ...
set -Eeuo pipefail

. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/adaptive-paths.sh"
setsid -f "$ADAPTIVE_REPO/scripts/adaptive-cast-launch.sh" "$@" >/dev/null 2>&1 </dev/null

case "${1:-}" in
    --toggle) echo "Casting to the TV (or stopping, if it was casting)" ;;
    --stop) echo "Stopped casting" ;;
    --freeze) echo "The TV holds the picture" ;;
    --curtain) echo "Curtain on the TV" ;;
    --resume) echo "The TV shows the screen again" ;;
    --wall) echo "The wall is on the TV" ;;
    *) echo "Done" ;;
esac
