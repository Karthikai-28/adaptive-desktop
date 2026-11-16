#!/usr/bin/env bash
# Install Air: control the desktop with your hands through the Kinect v1 (or the webcam).
#
#   scripts/install-air.sh            install whatever is missing
#   scripts/install-air.sh --status   say what is missing; change nothing
#
# It installs, all inside this checkout or your user account, no root:
#   libfreenect 0.7.5 built into .local/libfreenect      (kinect/build-libfreenect.sh)
#   MediaPipe 0.10.14 in a private venv, .local/air-venv  (hand landmarks, CPU only)
#   the adaptive-air user service                          (not started at login: Super+G)
#   the adaptive-kinect user service (the Kinect hub)      (on demand; stops itself when unused)
#   Kinect Studio in the app grid                          (camera, depth, point cloud, sensors)
# The "Kinect Camera" webcam needs a kernel module: scripts/install-virtual-cameras.sh (sudo).
# The Super+G shortcut is in scripts/install-keybindings.sh; the HUD is the shell's air.js.
# Needs cmake, gcc, libusb-1.0-0-dev and python3-venv (apt). The Kinect's USB devices must be
# readable by you (they are when /dev/bus/usb/*/* for 045e:02ae is rw for your user or group).
# Undo with ./uninstall.sh. See docs/AIR.md.
set -Eeuo pipefail
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/adaptive-paths.sh"
REPO="$ADAPTIVE_REPO"
UNIT="adaptive-air.service"
HUB_UNIT="adaptive-kinect.service"
APPS="$HOME/.local/share/applications"
STUDIO_ENTRY="com.karthi.KinectStudio.desktop"
UNIT_DIR="$HOME/.config/systemd/user"
VENV="$REPO/.local/air-venv"
PY_PACKAGES=("mediapipe==0.10.14" "numpy<2")

MODE=install
case "${1:-}" in
    --status) MODE=status ;;
    -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    '') ;;
    *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
esac

ok() { printf '  ok       %s\n' "$*"; }
need() { printf '  needed   %s\n' "$*"; MISSING=$((MISSING + 1)); }
MISSING=0

have_freenect() { [ -f "$REPO/.local/libfreenect/lib/libfreenect_sync.so" ]; }
have_venv() { "$VENV/bin/python" -c 'import mediapipe, cv2, numpy' 2>/dev/null; }

check() {
    MISSING=0
    have_freenect && ok "libfreenect $(cat "$REPO/.local/libfreenect/VERSION")" || need "libfreenect (kinect/build-libfreenect.sh)"
    have_venv && ok "MediaPipe in .local/air-venv" || need "MediaPipe venv (.local/air-venv)"
    [ -f "$UNIT_DIR/$UNIT" ] && ok "$UNIT installed (Super+G starts it)" || need "$UNIT"
    [ -f "$UNIT_DIR/$HUB_UNIT" ] && ok "$HUB_UNIT installed (the Kinect hub, on demand)" || need "$HUB_UNIT"
    [ -f "$APPS/$STUDIO_ENTRY" ] && ok "Kinect Studio in the app grid" || need "Kinect Studio app entry"
    if [ "$(cat /sys/devices/virtual/video4linux/video11/name 2>/dev/null)" = "Kinect Camera" ]; then
        ok "Kinect Camera webcam device (/dev/video11)"
    else
        printf '  optional %s\n' "Kinect Camera webcam: scripts/install-virtual-cameras.sh (sudo)"
    fi
    python3 "$REPO/services/adaptive-air/air.py" --probe | python3 -c '
import json, sys
p = json.load(sys.stdin)
if not p["present"]:
    print("  note     no Kinect on USB: Air will use the webcam")
elif p["camera"]:
    print("  ok       Kinect " + p["model"] + ": camera on USB")
else:
    print("  note     Kinect " + p["model"] + ": " + p["advice"])'
}

if [ "$MODE" = status ]; then
    check
    exit $((MISSING > 0))
fi

have_freenect || "$REPO/kinect/build-libfreenect.sh"

if ! have_venv; then
    echo "== MediaPipe (private venv, about 650 MB)"
    python3 -m venv --system-site-packages "$VENV"
    "$VENV/bin/pip" install --disable-pip-version-check --no-cache-dir -q --upgrade pip
    "$VENV/bin/pip" install --disable-pip-version-check --no-cache-dir -q "${PY_PACKAGES[@]}"
fi

mkdir -p "$UNIT_DIR"
adaptive_render "$REPO/services/$UNIT" "$UNIT_DIR/$UNIT"
adaptive_render "$REPO/services/$HUB_UNIT" "$UNIT_DIR/$HUB_UNIT"
mkdir -p "$APPS"
adaptive_render "$REPO/apps/kinect-studio/$STUDIO_ENTRY" "$APPS/$STUDIO_ENTRY"
update-desktop-database "$APPS" 2>/dev/null || true
systemctl --user daemon-reload
# A running Air picks up new code on its next start.
systemctl --user try-restart "$HUB_UNIT" "$UNIT" 2>/dev/null || true

check
