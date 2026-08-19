#!/usr/bin/env bash
set -Eeuo pipefail

#
# The screen goes black after ~30s and no setting stops it.
#
# gsd-power arms a 30-second blank timer, but only while it believes the
# screen saver is active. If it is told the saver came on and never told it
# went off, that timer stays armed for the rest of the session: the panel
# powers down 30 seconds after you stop typing, every time, and nothing in
# Settings has any effect because nothing in Settings is what is doing it.
#
# The give-away is an inconsistency - the display forced off while GNOME
# reports the screen saver inactive and X's own DPMS timeouts are all zero,
# so nothing legitimately asked for it.
#
#   --check    report the state, change nothing
#   (default)  repair it by restarting gsd-power
#

CHECK=0
[[ "${1:-}" == "--check" ]] && CHECK=1

if [[ -z "${DISPLAY:-}" ]]; then
    echo "no DISPLAY; nothing to check"
    exit 0
fi

saver_active() {
    gdbus call --session --dest org.gnome.ScreenSaver \
        --object-path /org/gnome/ScreenSaver \
        --method org.gnome.ScreenSaver.GetActive 2>/dev/null \
        | grep -q true
}

monitor_state() { xset q | awk '/Monitor is/ {print $3}'; }
dpms_enabled()  { xset q | grep -q "DPMS is Enabled"; }
dpms_timeouts() { xset q | awk '/Standby:/ {print $2 "/" $4 "/" $6}'; }

echo "Display blanking"
echo "  monitor:        $(monitor_state)"
echo "  DPMS:           $(dpms_enabled && echo enabled || echo disabled)"
echo "  DPMS timeouts:  $(dpms_timeouts)  (standby/suspend/off)"
echo "  screen saver:   $(saver_active && echo active || echo inactive)"
echo "  idle-delay:     $(gsettings get org.gnome.desktop.session idle-delay | awk '{print $NF}')s"

if pgrep -x gsd-power >/dev/null 2>&1; then
    echo "  gsd-power:      running (pid $(pgrep -x gsd-power | head -1))"
else
    echo "  gsd-power:      NOT running - brightness keys and battery"
    echo "                  warnings are gone with it"
fi

echo

# Blanking with every X timeout at zero and no screen saver on means something
# forced it rather than a timer expiring.
standby="$(xset q | awk '/Standby:/ {print $2}' | head -1)"

if [[ "$(monitor_state)" != "On" ]] \
    && ! saver_active \
    && [[ "${standby:-0}" == "0" ]]; then

    echo "The display is off while the screen saver is inactive and every X"
    echo "DPMS timeout is zero. Nothing asked for this - it is the stale"
    echo "gsd-power blank timer."

    if (( CHECK )); then
        exit 1
    fi

    echo "Restarting gsd-power to clear it."
    pkill -x gsd-power || true
    sleep 2

    if ! pgrep -x gsd-power >/dev/null 2>&1; then
        nohup /usr/libexec/gsd-power >/dev/null 2>&1 &
        sleep 2
    fi

    xset dpms force on

    if pgrep -x gsd-power >/dev/null 2>&1; then
        echo "gsd-power restarted; the display should stay on now."
    else
        echo "gsd-power did not come back. Log out and back in." >&2
        exit 1
    fi

    exit 0
fi

echo "Nothing forcing the display off right now."
echo
echo "This check only sees the fault while the screen is actually off, so run"
echo "it over SSH, or from a terminal a few seconds after the screen blanks."
