#!/usr/bin/env bash
# Let the phone's stylus be a drawing tablet on this computer: pressure, the
# eraser end, the side button (services/adaptive-link/pen.py).
#
# The tablet is made through /dev/uinput, which only root may write to. This
# gives it to whoever is at the computer's own seat (udev's uaccess, as for
# game controllers) and loads the uinput module at boot. It needs sudo, once.
#
# Not the input group: that would also let every program of the owner's read
# every keyboard - the lock screen's password included - which a pen does not
# need. (The touchpad gestures, scripts/adaptive-gestures.py, do need it.)
#
#   install-link-pen.sh            install
#   install-link-pen.sh --remove   take it out again
set -Eeuo pipefail

RULE=/etc/udev/rules.d/70-adaptive-link-pen.rules
LOAD=/etc/modules-load.d/adaptive-link-pen.conf

if [ "${1:-}" = "--remove" ]; then
    sudo rm -f "$RULE" "$LOAD"
    sudo udevadm control --reload-rules
    sudo udevadm trigger --name-match=uinput || true
    echo "The pen is a pointer again."
    exit 0
fi

# Before 73-seat-late.rules, which turns the uaccess tag into the seat's access.
echo 'KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess", OPTIONS+="static_node=uinput"' | sudo tee "$RULE" >/dev/null
echo "uinput" | sudo tee "$LOAD" >/dev/null
sudo modprobe uinput
sudo udevadm control --reload-rules
sudo udevadm trigger --name-match=uinput
sleep 1
if [ -w /dev/uinput ]; then
    echo "Done. The link needs restarting once: systemctl --user restart adaptive-link"
else
    echo "/dev/uinput is not open to $USER yet; log out and in again, then restart the link." >&2
fi
