#!/usr/bin/env bash
set -Eeuo pipefail

echo "========== OS =========="
. /etc/os-release
echo "$PRETTY_NAME"

echo
echo "========== NAUTILUS =========="
if command -v nautilus >/dev/null 2>&1; then
  nautilus --version || true
  dpkg-query -W -f='Package: ${Package}\nVersion: ${Version}\nStatus: ${Status}\n' nautilus 2>/dev/null || true
else
  echo "nautilus is not installed"
fi

echo
echo "========== GVFS =========="
dpkg -l | grep -E '^ii\s+(gvfs|gvfs-backends|gvfs-fuse|gvfs-daemons|gvfs-common)' || true

echo
echo "========== TRACKER =========="
dpkg -l | grep -E '^ii\s+(tracker|tracker-miner|tracker-extract)' || true

echo
echo "========== NAUTILUS EXTENSIONS =========="
dpkg -l | grep -E '^ii\s+.*nautilus.*(extension|python|terminal|admin|gtkhash)' || true

echo
echo "========== DIRECTORY HANDLER =========="
xdg-mime query default inode/directory 2>/dev/null || true

echo
echo "========== FILES SETTINGS =========="
for schema in \
  org.gnome.nautilus.preferences \
  org.gnome.nautilus.icon-view \
  org.gnome.nautilus.list-view
do
  if gsettings list-schemas | grep -qx "$schema"; then
    echo "--- $schema"
    gsettings list-recursively "$schema" || true
  fi
done

echo
echo "========== MOUNTS =========="
gio mount -l 2>/dev/null || true
