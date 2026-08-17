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
# Suspending instead would be the wrong fix: a docked laptop with the lid shut
# is still a working machine on the external display. Locking is the part that
# was missing, so that is the only thing this does.
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
        printf '%s lid closed - locking\n' "$(date -Is)" >>"$LOG_FILE"
        loginctl lock-session 2>>"$LOG_FILE" || true
    fi

    previous="$current"
done
