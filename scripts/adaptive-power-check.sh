#!/usr/bin/env bash
set -Eeuo pipefail

#
# Verify the machine can still go to sleep.
#
# Everything checked here was broken at once by a single feature, and the
# symptom was a hot laptop in a bag rather than an error on screen. See
# docs/POWER_POLICY.md.
#

POWER=org.gnome.settings-daemon.plugins.power
SESSION=org.gnome.desktop.session

fails=0

pass() { printf '  ok    %s\n' "$*"; }
fail() { printf '  FAIL  %s\n' "$*"; fails=$((fails + 1)); }

echo "Sleep paths"

battery_type="$(gsettings get $POWER sleep-inactive-battery-type)"
if [[ "$battery_type" == "'nothing'" ]]; then
    fail "battery suspend is disabled - the machine cannot sleep on battery"
else
    pass "battery suspend: $battery_type"
fi

idle_delay="$(gsettings get $SESSION idle-delay | awk '{print $NF}')"
if [[ "$idle_delay" == "0" ]]; then
    fail "idle-delay is 0 - the session never goes idle, so it never blanks"
else
    pass "idle delay: ${idle_delay}s"
fi

echo
echo "Display blanking"

if command -v xset >/dev/null 2>&1 && [[ -n "${DISPLAY:-}" ]]; then
    if xset q | grep -q "DPMS is Disabled"; then
        fail "DPMS is disabled - the panel never powers down"
    else
        pass "DPMS enabled"
    fi

    # X's own DPMS timers are deliberately left at 0 under GNOME: gsd-power
    # watches the idle monitor and switches DPMS modes itself, so a zero here
    # is normal and only means something if gsd-power is not the one blanking.
    standby="$(xset q | awk '/Standby:/ {print $2}' | head -1)"

    if pgrep -x gsd-power >/dev/null 2>&1; then
        pass "blanking owned by gsd-power (X standby: ${standby:-0}s)"
    elif [[ "${standby:-0}" == "0" ]]; then
        fail "gsd-power is not running and the X DPMS standby timeout is 0 -" \
             "nothing will power the panel down"
    else
        pass "DPMS standby: ${standby}s"
    fi
fi

echo
echo "Lid"

if pgrep -u "$UID" -f adaptive-lid-watch.sh >/dev/null 2>&1; then
    pass "lid watcher running"
else
    fail "lid watcher not running - closing the lid will not suspend"
fi

if [[ -f "${HOME}/.config/adaptive-desktop/clamshell" ]]; then
    echo "  note  clamshell opted in: the lid only locks while an external"
    echo "        display is connected"
fi

echo
echo "Inhibitors"

if command -v systemd-inhibit >/dev/null 2>&1; then
    # Anything of ours holding a sleep block would defeat all of the above.
    if systemd-inhibit --list 2>/dev/null | grep -i adaptive | grep -q block; then
        fail "an Adaptive process holds a block inhibitor"
        systemd-inhibit --list | grep -i adaptive | sed 's/^/        /'
    else
        pass "no Adaptive block inhibitors"
    fi
fi

echo
if (( fails )); then
    echo "$fails rule(s) broken - see docs/POWER_POLICY.md"
    exit 1
fi

echo "The machine can sleep."
