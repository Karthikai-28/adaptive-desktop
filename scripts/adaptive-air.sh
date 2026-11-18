#!/usr/bin/env bash
# Start and stop Air (hand-gesture control through the Kinect). Super+G runs --toggle.
#
#   scripts/adaptive-air.sh --toggle   start Air, or stop it if it is running
#   scripts/adaptive-air.sh --start | --stop
#   scripts/adaptive-air.sh --stop-all   stop everything using the Kinect (windows, Motion, Air, hub)
#   scripts/adaptive-air.sh --status   running or not, the camera in use, the Kinect on USB
#   scripts/adaptive-air.sh --demo     stop Air and play the scripted demo hands once (no camera)
#   scripts/adaptive-air.sh --studio   open Kinect Studio (camera, depth, point cloud, sensors)
#   scripts/adaptive-air.sh --webcam on|off   the Kinect's camera as the "Kinect Camera" webcam
#   scripts/adaptive-air.sh --led COLOUR   set the Kinect's LED (off, green, red, yellow,
#                                          blink-green, blink-red-yellow)
#   scripts/adaptive-air.sh --tilt DEG     tilt the Kinect (-27..27; needs its 12 V supply)
#
# docs/AIR.md.
set -Eeuo pipefail
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/adaptive-paths.sh"
UNIT=adaptive-air.service
PY="$ADAPTIVE_REPO/.local/air-venv/bin/python"
AIR="$ADAPTIVE_REPO/services/adaptive-air"

notify() { command -v notify-send >/dev/null && notify-send -a Air -i camera-web-symbolic "$@" || true; }

running() { systemctl --user is-active --quiet "$UNIT"; }

start() {
    if ! systemctl --user cat "$UNIT" >/dev/null 2>&1; then
        notify "Air is not installed" "Run scripts/install-air.sh"
        echo "Air is not installed: scripts/install-air.sh" >&2
        exit 1
    fi
    systemctl --user start "$UNIT"
}

case "${1:---toggle}" in
    --toggle) if running; then systemctl --user stop "$UNIT"; else start; fi ;;
    --start) start ;;
    --stop) systemctl --user stop "$UNIT" ;;
    --stop-all)
        # Everything that uses the Kinect: the windows first, then Motion and Air, then the hub they start.
        pkill -f "$ADAPTIVE_REPO/apps/kinect-motion/motion.py" || true
        pkill -f "$ADAPTIVE_REPO/apps/kinect-studio/studio.py" || true
        systemctl --user stop kinect-motion.service "$UNIT" adaptive-kinect.service 2>/dev/null || true
        echo "Kinect stopped: Fitness, Arcade, Room, Studio, Air and the hub" ;;
    --status)
        if running; then
            echo "Air: running"
            gdbus call --session -d org.adaptive.Air -o /org/adaptive/Air -m org.adaptive.Air.Status 2>/dev/null |
                python3 -c 'import ast, json, sys; print(json.dumps(json.loads(ast.literal_eval(sys.stdin.read().strip())[0]), indent=2))' ||
                true
        else
            echo "Air: stopped"
            python3 "$AIR/air.py" --probe
        fi ;;
    --demo)
        systemctl --user stop "$UNIT" 2>/dev/null || true
        exec python3 "$AIR/air.py" --demo ;;
    --studio)
        exec python3 "$ADAPTIVE_REPO/apps/kinect-studio/studio.py" ;;
    --webcam)
        case "${2:-}" in on) value=true ;; off) value=false ;; *) echo "--webcam on|off" >&2; exit 2 ;; esac
        systemctl --user start adaptive-kinect.service
        for _ in $(seq 30); do curl -fs http://127.0.0.1:8792/api/status >/dev/null && break; sleep 0.2; done
        curl -fs -X POST -H 'Content-Type: application/json' -d "{\"value\": $value}" \
            http://127.0.0.1:8792/api/webcam >/dev/null && echo "Kinect webcam: ${2}"
        [ "$value" = true ] && [ "$(cat /sys/devices/virtual/video4linux/video11/name 2>/dev/null)" != "Kinect Camera" ] &&
            echo "No Kinect Camera device yet: run scripts/install-virtual-cameras.sh once (sudo)." || true ;;
    --led)
        if curl -fs -X POST -H 'Content-Type: application/json' -d "{\"value\": \"${2:?colour}\"}" \
                http://127.0.0.1:8792/api/led >/dev/null 2>&1; then exit 0; fi
        python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import kinect; m = kinect.Motor(); ok = m.led(sys.argv[2]); m.close(); sys.exit(0 if ok else 1)' "$AIR" "${2:?colour}" ;;
    --tilt)
        if curl -fs -X POST -H 'Content-Type: application/json' -d "{\"value\": ${2:?degrees}}" \
                http://127.0.0.1:8792/api/tilt >/dev/null 2>&1; then exit 0; fi
        python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import kinect; m = kinect.Motor(); ok = m.tilt(float(sys.argv[2])); print(m.state()); m.close(); sys.exit(0 if ok else 1)' "$AIR" "${2:?degrees}" ;;
    -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//' ;;
    *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
esac
