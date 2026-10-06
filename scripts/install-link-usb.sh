#!/usr/bin/env bash
# Let Adaptive Link switch USB devices off and on from the phone.
#
# Whether a USB device may be used is the system's to say (the `authorized`
# file of each device under /sys/bus/usb/devices). This hands that switch to
# the people in the plugdev group - the person at the computer - with a udev
# rule, so it needs sudo once. Without it the phone still lists the devices
# and safely removes drives; it only cannot switch a device off.
#
# Only a device the system let in when it was plugged in is handed over. One
# it kept out (USBGuard, or authorized_default=0) stays the system's, so this
# can never be used to let in a device that was blocked.
#
#   install-link-usb.sh            install
#   install-link-usb.sh --remove   take it out again
set -Eeuo pipefail

RULE=/etc/udev/rules.d/71-adaptive-link-usb.rules

if [ "${1:-}" = "--remove" ]; then
    sudo rm -f "$RULE"
    sudo udevadm control --reload
    echo "Removed. The switches go back to the system at the next boot, or when a device is plugged in again."
    exit 0
fi

if ! id -nG | tr ' ' '\n' | grep -qx plugdev; then
    echo "You are not in the plugdev group: sudo usermod -aG plugdev $USER, then sign in again." >&2
    exit 1
fi

sudo tee "$RULE" >/dev/null <<'RULE'
# Adaptive Link: the person at the computer may switch a USB device off and on.
ACTION=="add|change", SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ATTR{bDeviceClass}!="09", ATTR{authorized}=="1", \
  RUN+="/bin/sh -c 'chgrp plugdev /sys%p/authorized && chmod 664 /sys%p/authorized'"
RULE
sudo udevadm control --reload
sudo udevadm trigger --subsystem-match=usb --action=change
echo "USB devices can now be switched off and on from the phone."
