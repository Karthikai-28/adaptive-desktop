#!/usr/bin/env bash
# Zero-State Protocol — permanently sanitize one explicitly named internal disk,
# leaving it unprovisioned.  This is for a separately booted, trusted environment.
#
# Default mode is a read-only plan.  It never selects a disk automatically.
set -Euo pipefail

MODE=plan
DISK=""
METHOD=""
CONFIRM=""

usage() {
    cat <<'EOF'
Usage:
  zero-state-protocol.sh --disk /dev/DEVICE [--plan]
  sudo env ZERO_STATE_EXTERNAL_BOOT=1 zero-state-protocol.sh --disk /dev/DEVICE \
       --method METHOD --execute --confirm "ZERO-STATE:DEVICE:SERIAL"

Methods:
  nvme-crypto-erase  NVMe controller crypto erase (all namespaces on that controller)
  nvme-block-erase   NVMe controller block erase (all namespaces on that controller)
  secure-discard     Device-supported secure discard of the selected disk

The default --plan mode is read-only.  --execute refuses the disk that backs
the running system, any disk with mounted partitions, and all calls without
the external-boot marker plus the exact confirmation phrase it prints.
EOF
}

fail() { printf 'Zero-State refused: %s\n' "$*" >&2; exit 2; }

while (($#)); do
    case "$1" in
        --disk) DISK="${2:-}"; shift 2 ;;
        --method) METHOD="${2:-}"; shift 2 ;;
        --confirm) CONFIRM="${2:-}"; shift 2 ;;
        --plan) MODE=plan; shift ;;
        --execute) MODE=execute; shift ;;
        -h|--help) usage; exit 0 ;;
        *) fail "unknown option: $1" ;;
    esac
done

[[ -n "$DISK" ]] || { usage >&2; fail "--disk is required"; }
[[ "$DISK" == /dev/* ]] || fail "--disk must be an absolute /dev path"
DISK="$(readlink -f -- "$DISK")"
[[ -b "$DISK" ]] || fail "$DISK is not a block device"
command -v lsblk >/dev/null || fail "lsblk is required"

TYPE="$(lsblk -dn -o TYPE "$DISK" 2>/dev/null | tr -d '[:space:]')"
[[ "$TYPE" == disk ]] || fail "$DISK is not a whole disk; never target a partition"

MOUNTS="$(lsblk -nrpo NAME,MOUNTPOINT "$DISK" | awk 'NF >= 2 && $2 != "" { print }')"
[[ -z "$MOUNTS" ]] || fail "$DISK or one of its partitions is mounted"

ROOT_SOURCE="$(findmnt -nro SOURCE / 2>/dev/null || true)"
ROOT_DISKS=()
if [[ "$ROOT_SOURCE" == /dev/* ]]; then
    ROOT_SOURCE="$(readlink -f -- "$ROOT_SOURCE")"
    # This walks device-mapper/LVM layers too, so an installed encrypted root
    # disk cannot be selected merely because / is mounted through /dev/mapper.
    while IFS=' ' read -r ROOT_NODE ROOT_TYPE; do
        [[ "$ROOT_TYPE" == disk ]] && ROOT_DISKS+=("$ROOT_NODE")
    done < <(lsblk -s -p -n -r -o NAME,TYPE "$ROOT_SOURCE" 2>/dev/null || true)
fi
for ROOT_DISK in "${ROOT_DISKS[@]}"; do
    [[ "$DISK" != "$ROOT_DISK" ]] || fail "the selected disk backs the running system; boot external media first"
done

NAME="$(basename "$DISK")"
SERIAL="$(lsblk -dn -o SERIAL "$DISK" 2>/dev/null | xargs)"
[[ -n "$SERIAL" ]] || SERIAL="NO-SERIAL"
PHRASE="ZERO-STATE:${NAME}:${SERIAL}"

printf 'Zero-State target: %s\n' "$DISK"
lsblk -dn -o NAME,SIZE,MODEL,SERIAL,TRAN "$DISK"
printf 'Required confirmation phrase: %s\n' "$PHRASE"

if [[ "$MODE" == plan ]]; then
    cat <<EOF

No data will be changed.  To execute from trusted external boot media, choose
one supported method after checking the drive documentation, then use exactly:
  sudo env ZERO_STATE_EXTERNAL_BOOT=1 $0 --disk $DISK --method METHOD --execute --confirm '$PHRASE'
EOF
    exit 0
fi

[[ "$EUID" -eq 0 ]] || fail "--execute requires root"
[[ "${ZERO_STATE_EXTERNAL_BOOT:-}" == 1 ]] || fail "set ZERO_STATE_EXTERNAL_BOOT=1 only after booting trusted external media"
[[ "$CONFIRM" == "$PHRASE" ]] || fail "confirmation phrase does not match this disk"
[[ -n "$METHOD" ]] || fail "--method is required with --execute"

# Re-check immediately before the irreversible operation.
MOUNTS="$(lsblk -nrpo NAME,MOUNTPOINT "$DISK" | awk 'NF >= 2 && $2 != "" { print }')"
[[ -z "$MOUNTS" ]] || fail "$DISK became mounted"

case "$METHOD" in
    nvme-crypto-erase|nvme-block-erase)
        [[ "$DISK" =~ ^/dev/nvme[0-9]+n[0-9]+$ ]] || fail "$METHOD requires an NVMe namespace disk"
        command -v nvme >/dev/null || fail "nvme-cli is required for $METHOD"
        CONTROLLER="${DISK%n*}"
        [[ -c "$CONTROLLER" ]] || fail "cannot find the NVMe controller for $DISK"
        ACTION="start-crypto-erase"
        [[ "$METHOD" == nvme-block-erase ]] && ACTION="start-block-erase"
        printf 'Starting %s on %s (controller %s). This is irreversible.\n' "$METHOD" "$DISK" "$CONTROLLER"
        sync
        nvme sanitize "$CONTROLLER" --sanact="$ACTION"
        ;;
    secure-discard)
        command -v blkdiscard >/dev/null || fail "blkdiscard is required for secure-discard"
        printf 'Starting secure discard on %s. This is irreversible.\n' "$DISK"
        sync
        blkdiscard --secure "$DISK"
        ;;
    *) fail "unsupported method: $METHOD" ;;
esac

printf 'Sanitization command completed for %s. Leave the device unprovisioned; do not reinstall an OS.\n' "$DISK"
