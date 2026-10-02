#!/usr/bin/env bash
# Set up the virtual camera Adaptive Link feeds the phone's camera into.
#
# It is a kernel module (v4l2loopback), so this is the one part of the link
# that needs sudo. It loads the module now and at every boot, as one device
# named "Phone Camera" that browsers and meeting apps list like any webcam.
#
#   install-link-camera.sh            install
#   install-link-camera.sh --remove   take it out again
set -Eeuo pipefail

CONF_LOAD=/etc/modules-load.d/adaptive-link-camera.conf
CONF_OPTS=/etc/modprobe.d/adaptive-link-camera.conf

if [ "${1:-}" = "--remove" ]; then
    sudo rm -f "$CONF_LOAD" "$CONF_OPTS"
    sudo modprobe -r v4l2loopback 2>/dev/null || true
    echo "The virtual camera is removed."
    exit 0
fi

if ! modinfo v4l2loopback >/dev/null 2>&1; then
    echo "Installing the v4l2loopback module..."
    sudo apt-get install -y v4l2loopback-dkms
fi

echo "v4l2loopback" | sudo tee "$CONF_LOAD" >/dev/null
# exclusive_caps makes browsers accept it as a camera; video_nr keeps its
# number steady across boots.
echo 'options v4l2loopback video_nr=10 card_label="Phone Camera" exclusive_caps=1' |
    sudo tee "$CONF_OPTS" >/dev/null
sudo modprobe -r v4l2loopback 2>/dev/null || true
sudo modprobe v4l2loopback
echo "Virtual camera: $(cat /sys/devices/virtual/video4linux/video10/name 2>/dev/null || echo 'not found') at /dev/video10"
