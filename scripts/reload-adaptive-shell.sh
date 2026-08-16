#!/usr/bin/env bash
set -Eeuo pipefail

UUID="adaptive-shell@local"
LIVE="$HOME/.local/share/gnome-shell/extensions/$UUID"

RESTART_SHELL=0
if [[ "${1:-}" == "--restart-shell" ]]; then
    RESTART_SHELL=1
fi

echo "Reloading $UUID ..."

gnome-extensions disable "$UUID" >/dev/null 2>&1 || true
sleep 1
gnome-extensions enable "$UUID"
sleep 2

gnome-extensions info "$UUID" | sed -n '1,30p'

# GNOME 42 caches an extension's JS module for the life of the shell process
# and ReloadExtension is deprecated, so disable/enable re-runs the code the
# shell already imported. Changed source needs a shell restart.
shell_pid="$(pgrep -x gnome-shell 2>/dev/null | head -1 || true)"
shell_started="1970-01-01T00:00:00"
if [[ -n "$shell_pid" && -d "/proc/$shell_pid" ]]; then
    shell_started="$(date -Is -d "@$(stat -c %Y "/proc/$shell_pid")")"
fi

newest_source="$(find "$LIVE" -name '*.js' -newermt "$shell_started" 2>/dev/null | head -1 || true)"

if [[ -n "$newest_source" ]]; then
    echo
    echo "Source is newer than the running shell: $newest_source"

    if [[ "$RESTART_SHELL" -eq 1 && "${XDG_SESSION_TYPE:-}" == "x11" ]]; then
        echo "Restarting GNOME Shell (X11, windows survive) ..."
        killall -3 gnome-shell
        sleep 8
        gnome-extensions info "$UUID" | sed -n '1,30p'
    else
        echo "Disable/enable does NOT load it. To apply:"
        echo "  X11:     $0 --restart-shell   (or press Alt+F2, type r, press Enter)"
        echo "  Wayland: log out and back into Adaptive Desktop"
    fi
fi
