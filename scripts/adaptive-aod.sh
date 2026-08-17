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
# Battery matters here: this is a laptop, and leaving the battery rules alone
# meant the machine suspended after 20 minutes and the display went black with
# no clock on it - which is the thing an always-on display is supposed to
# prevent. So battery inactivity is neutralised too. Closing the lid still
# suspends, which is the safety net that keeps an unattended laptop from
# running itself flat.
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

on_battery() {
    local supply
    for supply in /sys/class/power_supply/A{C,DP}*/online \
                  /sys/class/power_supply/*/online; do
        [[ -r "$supply" ]] || continue
        [[ "$(cat "$supply")" == "1" ]] && return 1
        return 0
    done
    return 1
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
    if command -v xset >/dev/null 2>&1 && [[ -n "${DISPLAY:-}" ]]; then
        echo "X DPMS:                   $(xset q | grep -c 'DPMS is Enabled') (1 = still enabled)"
    fi
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

    if on_battery; then
        echo "On battery - refusing." >&2
        echo "An always-on display on battery is how a laptop cooks in a bag." >&2
        echo "Plug in the mains and run this again." >&2
        exit 1
    fi

    mkdir -p "$STATE_DIR"

    if [[ ! -f "$STATE_FILE" ]]; then
        {
            echo "IDLE_DELAY='$(gsettings get $SESSION idle-delay)'"
            echo "AC_TYPE='$(gsettings get $POWER sleep-inactive-ac-type)'"
            echo "IDLE_DIM='$(gsettings get $POWER idle-dim)'"
            # xset's numeric timeouts, or "off" leaves DPMS enabled with every
            # timeout at zero - which never powers the panel down.
            echo "DPMS_TIMES='$(xset q | awk '/Standby:/ {print $2, $4, $6}')'"
            echo "SAVER_TIME='$(xset q | awk '/timeout:/ {print $2}')'"
        } > "$STATE_FILE"
    fi

    # No idle -> no blank, so the lock screen keeps showing.
    gsettings set $SESSION idle-delay 0
    gsettings set $POWER idle-dim false
    gsettings set $POWER sleep-inactive-ac-type nothing

    # Battery suspend is never disabled. Turning it off is what left this
    # laptop awake in a bag: no idle, no blank, no sleep, on battery. An
    # always-on display is a mains-power feature.

    # X keeps its own screen-saver and DPMS timers, independent of GNOME's
    # settings. They are usually zero here, but DPMS still reports itself as
    # enabled, and anything that pokes those timers later would blank a panel
    # that is supposed to stay lit. Turn them off outright.
    if command -v xset >/dev/null 2>&1 && [[ -n "${DISPLAY:-}" ]]; then
        xset s off
        xset s noblank
        xset -dpms
    fi

    echo "Always-on display enabled."
    echo "The session no longer auto-locks on idle - use Super+L."
    echo "Display stays lit on battery too; closing the lid still suspends."
    ;;
off)
    require_adaptive

    if [[ -f "$STATE_FILE" ]]; then
        # shellcheck disable=SC1090
        source "$STATE_FILE"
        gsettings set $SESSION idle-delay "${IDLE_DELAY##* }"
        gsettings set $POWER idle-dim "${IDLE_DIM//\'/}"
        gsettings set $POWER sleep-inactive-ac-type "${AC_TYPE//\'/}"
        # Battery suspend is never changed by "on", so there is nothing to
        # restore for it - and nothing that can leave the machine unable to
        # sleep on battery.
        if command -v xset >/dev/null 2>&1 && [[ -n "${DISPLAY:-}" ]]; then
            xset +dpms
            xset s on

            # Restore the numbers too. Re-enabling DPMS with zero timeouts
            # looks correct and still never blanks.
            times="${DPMS_TIMES//\'/}"
            if [[ -n "$times" && "$times" != "0 0 0" ]]; then
                xset dpms $times
            else
                xset dpms 300 600 900
            fi

            saver="${SAVER_TIME//\'/}"
            if [[ -n "$saver" && "$saver" != "0" ]]; then
                xset s "$saver"
            else
                xset s 300
            fi
        fi

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
