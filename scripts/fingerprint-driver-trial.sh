#!/usr/bin/env bash
# Temporarily try the locally built libfprint; restore the packaged daemon on exit.
# Uses only /run for the root-owned trial library and service override.
#   fingerprint-driver-trial.sh           administrator dialog, ten-minute trial
#   fingerprint-driver-trial.sh --stop    request immediate rollback
set -Eeuo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$REPO/.local/fingerprint-research"
LIB="$WORK/build/libfprint/libfprint-2.so.2.0.0"
DAEMON="$WORK/daemon-build/src/fprintd"
STOP="$WORK/stop-trial"
RUNTIME=/run/adaptive-fingerprint-trial
OVERRIDE=/run/systemd/system/fprintd.service.d/90-adaptive-driver-trial.conf

case "${1:-}" in
    --stop) mkdir -p "$WORK"; touch "$STOP"; exit 0 ;;
    --help|-h) sed -n '2,5p' "$0"; exit 0 ;;
    '') ;;
    *) echo 'Unknown option' >&2; exit 2 ;;
esac
[ -f "$LIB" ] || { echo 'Build the candidate library first.' >&2; exit 1; }
[ -x "$DAEMON" ] || { echo 'Build the candidate daemon first.' >&2; exit 1; }
LC_ALL=C readelf -d "$LIB" | grep -Fq 'Library soname: [libfprint-2.so.2]' || {
    echo 'Candidate does not have the expected libfprint ABI.' >&2; exit 1;
}
if [ "$EUID" -ne 0 ]; then
    rm -f "$STOP"
    exec pkexec /bin/bash "$0"
fi
[ ! -e "$RUNTIME" ] && [ ! -e "$OVERRIDE" ] || {
    echo 'A driver trial already exists; stop it before starting another.' >&2; exit 1;
}

cleanup() {
    trap - EXIT INT TERM
    rm -f "$OVERRIDE"
    systemctl daemon-reload
    systemctl restart fprintd.service || true
    rm -f "$RUNTIME/libfprint-2.so.2" "$RUNTIME/fprintd"
    rmdir "$RUNTIME" 2>/dev/null || true
    rmdir "$(dirname "$OVERRIDE")" 2>/dev/null || true
    echo 'Driver trial ended. The packaged libfprint is restored.'
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
install -d -m 0755 "$RUNTIME" "$(dirname "$OVERRIDE")"
install -o root -g root -m 0644 "$LIB" "$RUNTIME/libfprint-2.so.2"
install -o root -g root -m 0755 "$DAEMON" "$RUNTIME/fprintd"
printf '[Service]\nEnvironment=LD_LIBRARY_PATH=%s\nExecStart=\nExecStart=%s/fprintd\n' "$RUNTIME" "$RUNTIME" > "$OVERRIDE"
chmod 0644 "$OVERRIDE"
systemctl daemon-reload
systemctl restart fprintd.service
pid="$(systemctl show --property MainPID --value fprintd.service)"
grep -Fq "$RUNTIME/libfprint-2.so.2" "/proc/$pid/maps" || {
    echo 'The daemon did not load the trial library.' >&2; exit 1;
}
echo 'Trial library and daemon loaded. Test recognition in Settings; enroll a new finger if needed.'
echo 'Automatic rollback in ten minutes, or run this script with --stop.'
for ((i=0; i<120; i++)); do
    [ ! -e "$STOP" ] || break
    sleep 5
done
