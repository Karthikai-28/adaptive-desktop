#!/usr/bin/env bash
set -Eeuo pipefail

HOME_BASE="${HOME}"
STATE_FILE="${HOME}/.config/adaptive-desktop/last-v1.6-backup"
NEW_UUID="adaptive-shell-v16@local"

if [ ! -f "$STATE_FILE" ]; then
  echo "Missing backup pointer:"
  echo "  $STATE_FILE"
  exit 2
fi

BACKUP="$(cat "$STATE_FILE")"

if [ ! -d "$BACKUP" ]; then
  echo "Missing backup directory:"
  echo "  $BACKUP"
  exit 3
fi

gnome-extensions disable "$NEW_UUID" >/dev/null 2>&1 || true

# Remove v1.6 user routing files first.
rm -f \
  "${HOME}/.local/share/applications/org.gnome.Nautilus.desktop" \
  "${HOME}/.local/share/applications/com.karthi.AdaptiveFiles.desktop"

# Restore every backed-up home-relative item.
(
  cd "$BACKUP"
  find . -type f -o -type l
) | while read -r rel; do
  src="${BACKUP}/${rel#./}"
  dst="${HOME}/${rel#./}"
  mkdir -p "$(dirname "$dst")"
  cp -a "$src" "$dst"
done

# Restore prior default if there was no user desktop override backup.
if [ ! -f "${HOME}/.local/share/applications/org.gnome.Nautilus.desktop" ]; then
  xdg-mime default org.gnome.Nautilus.desktop inode/directory || true
fi

gnome-extensions enable adaptive-shell@local >/dev/null 2>&1 || true

echo "v1.6 rollback completed."
