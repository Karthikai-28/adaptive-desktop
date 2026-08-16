#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
NEW_UUID="adaptive-shell-v16@local"
OLD_UUID="adaptive-shell@local"
MARKER="${HOME}/.config/adaptive-desktop/v1.6.1-relogin-required"

echo "================================================================"
echo "POST-LOGIN v1.6.1"
echo "================================================================"

echo
echo "GNOME:"
gnome-shell --version

echo
echo "Checking new extension discovery..."

if ! gnome-extensions info \
  "$NEW_UUID" \
  >/dev/null 2>&1
then
  echo "ERROR: The restarted GNOME Shell still does not see:"
  echo "  $NEW_UUID"
  echo
  echo "Directory:"
  ls -la \
    "${HOME}/.local/share/gnome-shell/extensions/${NEW_UUID}" \
    || true
  exit 10
fi

echo "PASS: new UUID discovered by GNOME Shell"

gnome-extensions disable \
  "$OLD_UUID" \
  >/dev/null 2>&1 \
  || true

gnome-extensions enable "$NEW_UUID"

sleep 2

echo
echo "New extension state:"
gnome-extensions info "$NEW_UUID" \
  | sed -n '1,45p'

rm -f "$MARKER"

echo
echo "Running full v1.6.1 verification..."
"${REPO}/scripts/verify-v1.6.1.sh"
