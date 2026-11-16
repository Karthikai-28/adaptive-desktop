#!/usr/bin/env bash
# The virtual cameras browsers and meeting apps can pick, like any webcam (v4l2loopback):
#
#   /dev/video10  "Phone Camera"   the paired phone's camera (Adaptive Link)
#   /dev/video11  "Kinect Camera"  the Kinect's colour (or infrared) camera (the Kinect hub)
#
#   scripts/install-virtual-cameras.sh            install, load now and at every boot (sudo)
#   scripts/install-virtual-cameras.sh --status   what is loaded; change nothing
#   scripts/install-virtual-cameras.sh --remove   take both out again
#
# It is a kernel module, so this is the step that needs sudo. Both cameras are one module's
# options, so they are set up together here (scripts/install-link-camera.sh runs this).
set -Eeuo pipefail

CONF_LOAD=/etc/modules-load.d/adaptive-link-camera.conf
CONF_OPTS=/etc/modprobe.d/adaptive-link-camera.conf
OPTIONS='options v4l2loopback devices=2 video_nr=10,11 card_label="Phone Camera","Kinect Camera" exclusive_caps=1,1'

name_of() { cat "/sys/devices/virtual/video4linux/video$1/name" 2>/dev/null || echo "not loaded"; }

case "${1:-}" in
    --status)
        echo "/dev/video10: $(name_of 10)"
        echo "/dev/video11: $(name_of 11)"
        exit 0 ;;
    --remove)
        sudo rm -f "$CONF_LOAD" "$CONF_OPTS"
        sudo modprobe -r v4l2loopback 2>/dev/null || true
        echo "The virtual cameras are removed."
        exit 0 ;;
    '') ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
esac

if ! modinfo v4l2loopback >/dev/null 2>&1; then
    echo "Installing the v4l2loopback module..."
    sudo apt-get install -y v4l2loopback-dkms
fi

echo "v4l2loopback" | sudo tee "$CONF_LOAD" >/dev/null
# exclusive_caps makes browsers accept them as cameras; video_nr keeps their numbers steady.
echo "$OPTIONS" | sudo tee "$CONF_OPTS" >/dev/null

if [ "$(name_of 11)" = "Kinect Camera" ]; then
    echo "Both virtual cameras are already loaded."
elif sudo modprobe -r v4l2loopback 2>/dev/null; then
    sudo modprobe v4l2loopback
else
    echo "A virtual camera is in use (a call, or the phone camera), so the module cannot reload now."
    echo "Close what uses it and run this again, or restart: the new cameras load at boot."
fi
echo "/dev/video10: $(name_of 10)"
echo "/dev/video11: $(name_of 11)"
