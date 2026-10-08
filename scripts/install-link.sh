#!/usr/bin/env bash
# Install and start Adaptive Link (systemd user service).
#
# With no phone paired it listens on nothing; pair one with
#   scripts/link-cli.py pair
# Undo with: systemctl --user disable --now adaptive-link.service
set -Eeuo pipefail
REPO="${ADAPTIVE_REPO:-$HOME/adaptive-desktop}"
UNIT_DIR="$HOME/.config/systemd/user"

missing=()
for module in aiohttp cryptography; do
    python3 -c "import $module" 2>/dev/null || missing+=("$module")
done
if [ "${#missing[@]}" != 0 ]; then
    echo "Adaptive Link needs: ${missing[*]}" >&2
    echo "  pip install --user ${missing[*]}" >&2
    exit 1
fi
# The direct connection used away from home; without it the link is local only.
PYTHONPATH="$REPO/.local/link-pydeps" python3 -c "import aiortc" 2>/dev/null ||
    echo "note: away access needs aiortc (pip install --target $REPO/.local/link-pydeps aiortc)"
for tool in xdotool xclip; do
    command -v "$tool" >/dev/null || echo "note: $tool is not installed (sudo apt install $tool)"
done
# Phone apps run in a private display of their own, never on this screen.
for pair in Xvfb:xvfb xfwm4:xfwm4 dbus-daemon:dbus xauth:xauth xprop:x11-utils; do
    command -v "${pair%%:*}" >/dev/null ||
        echo "note: phone apps need ${pair%%:*} (sudo apt install ${pair#*:})"
done

mkdir -p "$UNIT_DIR"
install -m 0644 "$REPO/services/adaptive-link.service" "$UNIT_DIR/"
systemctl --user daemon-reload
# The service needs the session's display to show the screen and move the
# pointer; a unit started outside the graphical session has neither.
systemctl --user import-environment DISPLAY XAUTHORITY 2>/dev/null || true
systemctl --user enable --now adaptive-link.service
sleep 1
"$REPO/scripts/link-cli.py" status || true
