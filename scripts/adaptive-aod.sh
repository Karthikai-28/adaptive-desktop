#!/usr/bin/env bash
set -Eeuo pipefail

#
# Always-on display for the Adaptive lock screen.
#
# GNOME has no "keep showing the clock" switch: the shield appears on idle and
# the display is then powered down by the same idle timer. An always-on display
# therefore means telling the session not to go idle, which has two honest
# consequences worth knowing before turning it on:
#
#   * the session no longer auto-locks on idle - lock with Super+L;
#   * the panel stays lit, which costs power. True black helps a lot on OLED
#     because unlit pixels draw nothing, but it is not free.
#
# On battery the machine is still allowed to suspend, so an unattended laptop
# does not run itself flat holding a clock on screen.
#
# Previous values are saved so `off` restores exactly what was there before.
#

STATE_DIR="${HOME}/.local/state/adaptive-desktop"
STATE_FILE="${STATE_DIR}/aod-previous.env"

SESSION=org.gnome.desktop.session
POWER=org.gnome.settings-daemon.plugins.power

usage() {
    echo "usage: $(basename "$0") on|off|status"
    exit 2
}

require_adaptive() {
    if [[ "${DCONF_PROFILE:-}" != "adaptive" ]]; then
        echo "Not inside the Adaptive session (DCONF_PROFILE='${DCONF_PROFILE:-}')." >&2
        echo "Refusing to change the normal Ubuntu session's power settings." >&2
        exit 1
    fi
}

status() {
    echo "idle-delay:               $(gsettings get $SESSION idle-delay)"
    echo "sleep-inactive-ac-type:   $(gsettings get $POWER sleep-inactive-ac-type)"
    echo "sleep-inactive-batt-type: $(gsettings get $POWER sleep-inactive-battery-type)"
    echo "idle-dim:                 $(gsettings get $POWER idle-dim)"
    echo "lock-enabled:             $(gsettings get org.gnome.desktop.screensaver lock-enabled)"

    if [[ -f "$STATE_FILE" ]]; then
        echo
        echo "always-on display: ON (saved state at $STATE_FILE)"
    else
        echo
        echo "always-on display: off"
    fi
}

case "${1:-}" in
on)
    require_adaptive
    mkdir -p "$STATE_DIR"

    if [[ ! -f "$STATE_FILE" ]]; then
        {
            echo "IDLE_DELAY=$(gsettings get $SESSION idle-delay)"
            echo "AC_TYPE=$(gsettings get $POWER sleep-inactive-ac-type)"
            echo "IDLE_DIM=$(gsettings get $POWER idle-dim)"
        } > "$STATE_FILE"
    fi

    # No idle -> no blank, so the lock screen keeps showing.
    gsettings set $SESSION idle-delay 0
    gsettings set $POWER idle-dim false
    gsettings set $POWER sleep-inactive-ac-type nothing
    # Battery deliberately left alone: an unattended laptop should still sleep.

    echo "Always-on display enabled."
    echo "The session no longer auto-locks on idle - use Super+L."
    ;;
off)
    require_adaptive

    if [[ -f "$STATE_FILE" ]]; then
        # shellcheck disable=SC1090
        source "$STATE_FILE"
        gsettings set $SESSION idle-delay "${IDLE_DELAY##* }"
        gsettings set $POWER idle-dim "$IDLE_DIM"
        gsettings set $POWER sleep-inactive-ac-type "$AC_TYPE"
        rm -f "$STATE_FILE"
        echo "Always-on display disabled; previous settings restored."
    else
        gsettings reset $SESSION idle-delay
        gsettings reset $POWER idle-dim
        gsettings reset $POWER sleep-inactive-ac-type
        echo "No saved state; reset to GNOME defaults."
    fi
    ;;
status)
    status
    ;;
*)
    usage
    ;;
esac
