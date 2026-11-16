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

# Both virtual cameras (the phone's and the Kinect's) are one module's options.
exec "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/install-virtual-cameras.sh"
