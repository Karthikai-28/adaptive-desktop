#!/usr/bin/env bash
# Small-sensor fingerprint matching for the Validity VFS7552 (138a:0091).
#
#   install-fingerprint-driver.sh            build if needed, install (administrator dialog)
#   install-fingerprint-driver.sh --status   installed / outdated / not installed; no changes
#   install-fingerprint-driver.sh --remove   back to Ubuntu's packaged libfprint
#
# Ubuntu's fprintd, pam_fprintd, GDM and sudo configuration stay untouched: one
# systemd drop-in makes fprintd load the patched library from /opt (fprintd runs
# with ProtectHome, so it cannot be in the checkout). Password login is never
# affected. Fingers enrolled with one matcher do not match with the other:
# enroll again after installing or removing. docs/FINGERPRINT.md
set -Eeuo pipefail
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/adaptive-paths.sh"

BUILT="$ADAPTIVE_REPO/.local/fingerprint-driver/libfprint-2.so.2"
RUNTIME=/opt/adaptive-fingerprint
LIB="$RUNTIME/libfprint-2.so.2"
DROPIN=/etc/systemd/system/fprintd.service.d/50-adaptive-libfprint.conf
READER=138a:0091

status() {
    if [ ! -f "$DROPIN" ] || [ ! -f "$LIB" ]; then
        echo "not installed"; return 1
    fi
    if [ -f "$BUILT" ] && ! cmp -s "$BUILT" "$LIB"; then
        echo "installed, but the build in .local/fingerprint-driver is newer"; return 1
    fi
    echo "installed ($LIB)"
}

loaded() {
    local pid
    systemctl start fprintd.service
    pid="$(systemctl show --property MainPID --value fprintd.service)"
    [ "$pid" -gt 0 ] && grep -Fq "$LIB" "/proc/$pid/maps"
}

as_root() {
    case "$1" in
        install)
            install -d -m 0755 "$RUNTIME" "$(dirname "$DROPIN")"
            install -o root -g root -m 0644 "$2" "$LIB.new"
            mv -f "$LIB.new" "$LIB"
            printf '%s\n' \
                '# Adaptive Desktop: small-sensor matching for the VFS7552 (docs/FINGERPRINT.md).' \
                '# Remove with scripts/install-fingerprint-driver.sh --remove' \
                '[Service]' "Environment=LD_LIBRARY_PATH=$RUNTIME" > "$DROPIN"
            chmod 0644 "$DROPIN"
            systemctl daemon-reload
            systemctl stop fprintd.service 2>/dev/null || true
            if ! loaded; then
                echo "fprintd did not load $LIB; restoring the packaged library." >&2
                as_root remove
                exit 1
            fi
            echo "fprintd is using the small-sensor matcher." ;;
        remove)
            rm -f "$DROPIN" "$LIB"
            rmdir "$RUNTIME" "$(dirname "$DROPIN")" 2>/dev/null || true
            systemctl daemon-reload
            systemctl stop fprintd.service 2>/dev/null || true
            echo "Ubuntu's packaged libfprint is back in use." ;;
    esac
}

case "${1:-}" in
    --status) status; exit ;;
    --as-root) [ "$EUID" -eq 0 ] || exit 1; shift; as_root "$@"; exit ;;
    --remove)
        [ -e "$DROPIN" ] || [ -e "$LIB" ] || { echo "Not installed."; exit 0; }
        pkexec /bin/bash "$(readlink -f "$0")" --as-root remove
        echo "Enroll your fingers again: prints made with the small-sensor matcher do not match with the packaged one." ;;
    --help|-h) sed -n '2,11p' "$0" ;;
    '')
        lsusb -d "$READER" >/dev/null 2>&1 || {
            echo "No VFS7552 ($READER) reader here; the packaged libfprint is right for other readers." >&2; exit 1; }
        [ -f "$BUILT" ] || "$ADAPTIVE_REPO/fingerprint/build-driver.sh"
        if status >/dev/null; then echo "Already installed."; exit 0; fi
        pkexec /bin/bash "$(readlink -f "$0")" --as-root install "$BUILT"
        echo "Now enroll your fingers again in Adaptive Settings > Fingerprint unlock (12 touches each)." ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
esac
