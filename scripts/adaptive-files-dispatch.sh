#!/usr/bin/env bash
set -Eeuo pipefail

#
# Chooses which Nautilus answers a file-manager request.
#
# Inside Adaptive Desktop the forked Nautilus is the session's file manager, so
# folders opened from anywhere land in one window with our skin. Every other
# session - normal Ubuntu above all - keeps stock Nautilus untouched, which is
# why this dispatcher exists instead of a plain D-Bus service file pointing
# straight at the fork.
#
# Same session guard as scripts/project-context-autostart.sh.
#

REPO="${HOME}/adaptive-desktop"
FORK="${REPO}/.local/adaptive-nautilus/bin/nautilus"
STOCK="/usr/bin/nautilus"
LOG_DIR="${HOME}/.local/state/adaptive-desktop"
LOG_FILE="${LOG_DIR}/files-dispatch.log"

mkdir -p "$LOG_DIR"

in_adaptive_session() {
  [[ "${DCONF_PROFILE:-}" == "adaptive" \
    || "${GDMSESSION:-}" == "adaptive-desktop" \
    || "${XDG_SESSION_DESKTOP:-}" == "adaptive-desktop" ]]
}

if in_adaptive_session && [[ -x "$FORK" ]]; then
  BIN="$FORK"
  WHICH="adaptive"
else
  BIN="$STOCK"
  WHICH="stock"
fi

printf '%s %s %s %s\n' "$(date -Is)" "$WHICH" "$BIN" "$*" >>"$LOG_FILE"

exec "$BIN" "$@"
