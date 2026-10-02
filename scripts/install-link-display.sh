#!/usr/bin/env bash
# Let the phone be another display: the desktop extended onto it.
#
# The desktop only extends onto displays the graphics driver has, and this
# computer has no output it can light with nothing plugged in. evdi is a
# kernel module (the one DisplayLink docks use) that adds a display made by
# a program - the link, which says a monitor of the phone's size has been
# plugged in. Loading a kernel module needs root, so this needs sudo, once.
#
#   install-link-display.sh            install
#   install-link-display.sh --remove   take it out again
set -Eeuo pipefail

CONF_LOAD=/etc/modules-load.d/adaptive-link-display.conf
CONF_OPTS=/etc/modprobe.d/adaptive-link-display.conf

if [ "${1:-}" = "--remove" ]; then
    sudo rm -f /etc/modules-load.d/adaptive-link-display.conf /etc/modprobe.d/adaptive-link-display.conf
    sudo modprobe -r evdi 2>/dev/null || true
    echo "The phone's display is removed. (The evdi package itself is left: sudo apt remove evdi-dkms libevdi0)"
    exit 0
fi

if ! modinfo evdi >/dev/null 2>&1 || ! ldconfig -p | grep -q libevdi; then
    echo "Installing evdi..."
    sudo apt-get install -y evdi-dkms libevdi0
fi

echo "evdi" | sudo tee "$CONF_LOAD" >/dev/null
# One device, there from boot: the display the phone becomes.
echo "options evdi initial_device_count=1" | sudo tee "$CONF_OPTS" >/dev/null
sudo modprobe -r evdi 2>/dev/null || true
sudo modprobe evdi initial_device_count=1
if [ -d /sys/devices/evdi ]; then
    echo "Done. In the app: Screen → the menu → \"Use this phone as another display\"."
    echo "The link needs restarting once to see it: systemctl --user restart adaptive-link"
else
    echo "evdi did not load. If Secure Boot is on, the module has to be signed: see 'mokutil --sb-state'." >&2
    exit 1
fi
