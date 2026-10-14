#!/usr/bin/env bash
# Read-only checks for the irreversible Zero-State script.
set -Euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$REPO/scripts/zero-state-protocol.sh"

bash -n "$SCRIPT"
"$SCRIPT" --help >/dev/null
if "$SCRIPT" --disk /dev/null --plan >/dev/null 2>&1; then
    echo "Zero-State accepted a non-disk target" >&2
    exit 1
fi
rg -q 'MODE=plan' "$SCRIPT"
rg -q 'ZERO_STATE_EXTERNAL_BOOT' "$SCRIPT"
rg -q 'confirmation phrase does not match' "$SCRIPT"
rg -q 'the selected disk backs the running system' "$SCRIPT"
echo "Zero-State protocol guards verified"
