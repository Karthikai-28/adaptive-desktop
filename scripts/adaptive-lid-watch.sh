#!/usr/bin/env bash
set -Eeuo pipefail

#
# Lock the session when the lid closes.
#
# GNOME will not do it here. gsd-power takes a block inhibitor on
# handle-lid-switch whenever an external monitor is attached ("External monitor
# attached or configuration changed recently"), and
# lid-close-suspend-with-external-monitor is false, so closing the lid on a
# docked machine does nothing at all - no suspend, and therefore no lock.
#
# Locking alone was the wrong call. A laptop with the lid shut goes to sleep -
# that is what every other machine does, and what stops it cooking in a bag. So
# the lid suspends, after locking so the screen is never left unlocked on wake.
#
# Clamshell use - lid shut, working on an external display - is opt-in, because
# defaulting to it is how a laptop ends up awake in a bag:
#
#     touch ~/.config/adaptive-desktop/clamshell
#
# With that file present the lid only locks, and only while an external display
# is actually connected. Pull the display and the lid suspends again.
#
# Watches the ACPI lid state rather than logind's LidClosed property, because
# login1 does not emit a change signal for it - a property that has to be
# polled anyway is better polled from here than from inside GNOME Shell.
#

INTERVAL="${ADAPTIVE_LID_INTERVAL:-2}"
LOG_DIR="${HOME}/.local/state/adaptive-desktop"
LOG_FILE="${LOG_DIR}/lid-watch.log"

mkdir -p "$LOG_DIR"

in_adaptive_session() {
    [[ "${DCONF_PROFILE:-}" == "adaptive" ]] \
        || [[ "${GDMSESSION:-}" == "adaptive-desktop" ]] \
        || [[ "${XDG_SESSION_DESKTOP:-}" == "adaptive-desktop" ]]
}

if ! in_adaptive_session; then
    printf '%s skipped outside the Adaptive session\n' "$(date -Is)" >>"$LOG_FILE"
    exit 0
fi

# Overridable so the close transition can be exercised without a hinge.
LID_GLOB="${ADAPTIVE_LID_GLOB:-/proc/acpi/button/lid/*/state}"

external_display_connected() {
    # "connected" without "disconnected"; xrandr prints both words.
    xrandr --query 2>/dev/null \
        | grep -vE "^eDP|^LVDS" \
        | grep -qE "^[A-Za-z0-9-]+ connected"
}

clamshell_wanted() {
    [[ -f "${HOME}/.config/adaptive-desktop/clamshell" ]] \
        && external_display_connected
}

lid_state() {
    local file
    for file in $LID_GLOB; do
        [[ -r "$file" ]] || continue
        awk '{print $2}' "$file"
        return 0
    done
    return 1
}

if ! lid_state >/dev/null 2>&1; then
    printf '%s no ACPI lid device; watcher not started\n' "$(date -Is)" >>"$LOG_FILE"
    exit 0
fi

printf '%s lid watcher started (interval %ss)\n' "$(date -Is)" "$INTERVAL" >>"$LOG_FILE"

previous="$(lid_state)"

while sleep "$INTERVAL"; do
    current="$(lid_state 2>/dev/null || echo "$previous")"

    # Only the moment of closing matters. Locking repeatedly while the lid
    # stays shut would fight anything else touching the session.
    if [[ "$previous" == "open" && "$current" == "closed" ]]; then
        loginctl lock-session 2>>"$LOG_FILE" || true

        if clamshell_wanted; then
            printf '%s lid closed - clamshell, locked only\n' \
                "$(date -Is)" >>"$LOG_FILE"
        else
            printf '%s lid closed - locking and suspending\n' \
                "$(date -Is)" >>"$LOG_FILE"
            systemctl suspend 2>>"$LOG_FILE" || true
        fi
    fi

    previous="$current"
done
