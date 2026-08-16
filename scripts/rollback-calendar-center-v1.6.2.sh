#!/usr/bin/env bash
set -Eeuo pipefail

UUID="adaptive-shell-v16@local"
LIVE="${HOME}/.local/share/gnome-shell/extensions/${UUID}/stylesheet.css"
STATE_FILE="${HOME}/.config/adaptive-desktop/last-v1.6.2-calendar-backup"

if [ ! -f "$STATE_FILE" ]; then
  echo "No v1.6.2 backup pointer found."
  exit 2
fi

BACKUP="$(cat "$STATE_FILE")"

test -f "${BACKUP}/stylesheet.css"

gnome-extensions disable "$UUID" >/dev/null 2>&1 || true

cp -a \
  "${BACKUP}/stylesheet.css" \
  "$LIVE"

gnome-extensions enable "$UUID" >/dev/null 2>&1 || true

echo "Calendar/notification styling rolled back."
