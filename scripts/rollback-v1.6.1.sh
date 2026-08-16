#!/usr/bin/env bash
set -Eeuo pipefail

STATE_FILE="${HOME}/.config/adaptive-desktop/last-v1.6.1-backup"
NEW_UUID="adaptive-shell-v16@local"
OLD_UUID="adaptive-shell@local"

if [ ! -f "$STATE_FILE" ]; then
  echo "Missing v1.6.1 backup pointer:"
  echo "  $STATE_FILE"
  exit 2
fi

BACKUP="$(cat "$STATE_FILE")"

if [ ! -d "$BACKUP" ]; then
  echo "Missing backup directory:"
  echo "  $BACKUP"
  exit 3
fi

gnome-extensions disable \
  "$NEW_UUID" \
  >/dev/null 2>&1 \
  || true

rm -rf \
  "${HOME}/.local/share/gnome-shell/extensions/${NEW_UUID}"

rm -f \
  "${HOME}/.local/share/applications/org.gnome.Nautilus.desktop" \
  "${HOME}/.local/share/applications/com.karthi.AdaptiveFiles.desktop"

(
  cd "$BACKUP"
  find . -type f -o -type l
) | while read -r rel; do
  case "$rel" in
    ./enabled-extensions.txt)
      continue
      ;;
  esac

  src="${BACKUP}/${rel#./}"
  dst="${HOME}/${rel#./}"

  mkdir -p "$(dirname "$dst")"
  cp -a "$src" "$dst"
done

if [ -f "${BACKUP}/enabled-extensions.txt" ]; then
  PREVIOUS="$(
    cat "${BACKUP}/enabled-extensions.txt"
  )"

  gsettings set \
    org.gnome.shell \
    enabled-extensions \
    "$PREVIOUS"
fi

rm -f \
  "${HOME}/.config/adaptive-desktop/v1.6.1-relogin-required"

echo "v1.6.1 rollback staged."
echo "Log out/in once if the shell UI does not immediately reflect it."
