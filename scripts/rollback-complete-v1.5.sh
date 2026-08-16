#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
PREFIX="${REPO}/.local/adaptive-nautilus"
UUID="adaptive-shell@local"
LIVE_EXT="${HOME}/.local/share/gnome-shell/extensions/${UUID}"
STATE_FILE="${HOME}/.config/adaptive-desktop/last-complete-patch-backup"

if [ ! -f "$STATE_FILE" ]; then
  echo "No complete-patch backup pointer found:"
  echo "  $STATE_FILE"
  exit 2
fi

BACKUP="$(cat "$STATE_FILE")"

if [ ! -d "$BACKUP" ]; then
  echo "Backup directory is missing:"
  echo "  $BACKUP"
  exit 3
fi

echo "Restoring:"
echo "  $BACKUP"

gnome-extensions disable "$UUID" >/dev/null 2>&1 || true

if [ -d "${BACKUP}/gnome-shell/${UUID}" ]; then
  rm -rf "$LIVE_EXT"
  mkdir -p "$(dirname "$LIVE_EXT")"
  cp -a "${BACKUP}/gnome-shell/${UUID}" "$LIVE_EXT"
fi

if [ -d "${BACKUP}/adaptive-nautilus" ]; then
  (
    cd "${BACKUP}/adaptive-nautilus"
    find . -type f -o -type l
  ) | while read -r rel; do
    src="${BACKUP}/adaptive-nautilus/${rel#./}"
    dst="${PREFIX}/${rel#./}"
    mkdir -p "$(dirname "$dst")"
    cp -a "$src" "$dst"
  done
fi

if [ -f "${BACKUP}/desktop/com.karthi.AdaptiveFiles.desktop" ]; then
  mkdir -p "${HOME}/.local/share/applications"
  cp -a \
    "${BACKUP}/desktop/com.karthi.AdaptiveFiles.desktop" \
    "${HOME}/.local/share/applications/"
fi

gnome-extensions enable "$UUID" >/dev/null 2>&1 || true

echo
echo "Rollback complete."
echo "Log out/in only if GNOME Shell does not visually refresh."
