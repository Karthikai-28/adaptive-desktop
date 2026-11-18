#!/usr/bin/env bash
# Install the Kinect app (Fitness, Games, Camera, Room, Scan, History) and Kinect Motion behind it.
#
#   scripts/install-kinect-motion.sh            install whatever is missing
#   scripts/install-kinect-motion.sh --status   say what is missing; change nothing
#   scripts/install-kinect-motion.sh --pad      also let Kinect Pad make a virtual gamepad
#                                               (a udev rule for /dev/uinput; asks for sudo once)
#
# Needs Air installed first (the Kinect hub, libfreenect, MediaPipe and its models): ./install.sh
# --only air. This adds, in your user account only:
#   the kinect-motion user service      (on demand; stops a minute after the last page closes)
#   Kinect                              one launcher in the app grid (the old Kinect Fitness,
#                                       Arcade, Room and Studio launchers are removed; their
#                                       commands still open the same sections of it)
#   python-libevdev in the Air venv     (Kinect Pad)
# Workout history: ~/.local/share/adaptive-desktop/fitness.db (results only, never pictures).
# Undo with ./uninstall.sh. See docs/KINECT_MOTION.md.
set -Eeuo pipefail
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/adaptive-paths.sh"
REPO="$ADAPTIVE_REPO"
UNIT="kinect-motion.service"
UNIT_DIR="$HOME/.config/systemd/user"
APPS="$HOME/.local/share/applications"
ENTRY=com.karthi.Kinect.desktop
OLD_ENTRIES=(com.karthi.KinectFitness.desktop com.karthi.KinectArcade.desktop com.karthi.KinectRoom.desktop
             com.karthi.KinectStudio.desktop)
VENV="$REPO/.local/air-venv"
RULE=/etc/udev/rules.d/70-kinect-pad-uinput.rules

MODE=install
case "${1:-}" in
    --status) MODE=status ;;
    --pad) MODE=pad ;;
    -h|--help) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
esac

MISSING=0
ok() { printf '  ok       %s\n' "$1"; }
need() { printf '  needed   %s\n' "$1"; MISSING=$((MISSING + 1)); }

check() {
    echo "Kinect Motion"
    [ -x "$VENV/bin/python" ] && ok "Air venv" || need "Air (./install.sh --only air)"
    [ -f "$UNIT_DIR/$UNIT" ] && ok "kinect-motion user service" || need "kinect-motion user service"
    [ -f "$APPS/$ENTRY" ] && ok "Kinect in the app grid" || need "Kinect app launcher"
    for e in "${OLD_ENTRIES[@]}"; do
        [ -f "$APPS/$e" ] && need "remove the old ${e#com.karthi.} launcher" || true
    done
    if "$VENV/bin/python" -c 'import libevdev' 2>/dev/null; then ok "python-libevdev (Kinect Pad)"; else need "python-libevdev"; fi
    if [ -w /dev/uinput ]; then ok "Kinect Pad can make a virtual gamepad (/dev/uinput)"
    else printf '  optional %s\n' "Kinect Pad: scripts/install-kinect-motion.sh --pad (sudo once)"; fi
}

if [ "$MODE" = status ]; then
    check
    exit $((MISSING > 0))
fi

if [ "$MODE" = pad ]; then
    # Only /dev/uinput, only for the input group (you are in it), not every device.
    echo 'KERNEL=="uinput", SUBSYSTEM=="misc", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"' |
        sudo tee "$RULE" >/dev/null
    sudo udevadm control --reload-rules
    sudo udevadm trigger --name-match=uinput 2>/dev/null || true
    id -nG | grep -qw input || sudo usermod -aG input "$USER"
    echo "Kinect Pad: /dev/uinput is now writable by the input group (log out and in if you were just added)."
fi

[ -x "$VENV/bin/python" ] || { echo "Install Air first: ./install.sh --only air" >&2; exit 1; }
"$VENV/bin/python" -c 'import libevdev' 2>/dev/null ||
    "$VENV/bin/pip" install --disable-pip-version-check --no-cache-dir -q "libevdev==0.11"

mkdir -p "$UNIT_DIR" "$APPS"
adaptive_render "$REPO/services/$UNIT" "$UNIT_DIR/$UNIT"
adaptive_render "$REPO/apps/kinect/$ENTRY" "$APPS/$ENTRY"
for e in "${OLD_ENTRIES[@]}"; do rm -f "$APPS/$e"; done
update-desktop-database "$APPS" 2>/dev/null || true
systemctl --user daemon-reload
systemctl --user try-restart "$UNIT" 2>/dev/null || true

check
