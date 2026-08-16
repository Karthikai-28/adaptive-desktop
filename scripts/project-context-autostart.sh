#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
LOG_DIR="${HOME}/.local/state/adaptive-desktop"
LOG_FILE="${LOG_DIR}/project-context-autostart.log"

mkdir -p "$LOG_DIR"

if [[ "${DCONF_PROFILE:-}" != "adaptive" \
  && "${GDMSESSION:-}" != "adaptive-desktop" \
  && "${XDG_SESSION_DESKTOP:-}" != "adaptive-desktop" ]]; then
  {
    printf '%s skipped outside Adaptive session\n' "$(date -Is)"
    printf '  DCONF_PROFILE=%s GDMSESSION=%s XDG_SESSION_DESKTOP=%s\n' \
      "${DCONF_PROFILE:-}" "${GDMSESSION:-}" "${XDG_SESSION_DESKTOP:-}"
  } >>"$LOG_FILE"
  exit 0
fi

exec "${REPO}/services/project-context/main.py" >>"$LOG_FILE" 2>&1
