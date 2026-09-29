#!/usr/bin/env bash
set -Eeuo pipefail

# Install the touchpad gesture service and its settings app for this user,
# then restart the service so the new code and settings are live.
#
#   service   scripts/adaptive-gestures.py --daemon   (autostarted at login)
#   settings  apps/adaptive-gestures                  ("Touchpad Gestures")

REPO="${ADAPTIVE_REPO:-$HOME/adaptive-desktop}"
APPS="$HOME/.local/share/applications"
AUTOSTART="$HOME/.config/autostart"

mkdir -p "$APPS" "$AUTOSTART"
install -m 0644 "$REPO/apps/adaptive-gestures/com.karthi.AdaptiveGestures.desktop" "$APPS/"
update-desktop-database "$APPS" 2>/dev/null || true

cat > "$AUTOSTART/adaptive-gestures.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Adaptive Gestures
Comment=Three- and four-finger touchpad gestures on X11
Exec=$REPO/scripts/adaptive-gestures.py --daemon
Hidden=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
DESKTOP

# Restart the service. Only python3 processes running the daemon are
# stopped: matching on command-line text alone also hits any shell whose
# command happens to mention the script, including the one running this.
for pid in $(pgrep -x python3 || true); do
    if tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q "adaptive-gestures\.py"; then
        kill "$pid" 2>/dev/null || true
    fi
done
sleep 0.5
setsid "$REPO/scripts/adaptive-gestures.py" --daemon >/dev/null 2>&1 < /dev/null &

echo "Installed:"
echo "  $APPS/com.karthi.AdaptiveGestures.desktop"
echo "  $AUTOSTART/adaptive-gestures.desktop"
echo "Gesture service restarted. Check it with:"
echo "  $REPO/scripts/adaptive-gestures.py --doctor"
