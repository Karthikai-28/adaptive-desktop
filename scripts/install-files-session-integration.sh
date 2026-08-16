#!/usr/bin/env bash
set -Eeuo pipefail

#
# Makes the forked Nautilus the file manager of the Adaptive session.
#
# The session bus fixes its service directories at startup, before the session
# wrapper runs, so XDG_DATA_DIRS alone cannot redirect D-Bus activation.
# XDG_DATA_HOME is always searched and wins over /usr/share, so the two service
# files below are what actually decide which binary answers.
#
# Both point at the dispatcher, which falls back to stock Nautilus outside
# Adaptive Desktop - that is what keeps the normal Ubuntu session unchanged.
#

REPO="${HOME}/adaptive-desktop"
DISPATCH="${REPO}/scripts/adaptive-files-dispatch.sh"
SERVICE_DIR="${HOME}/.local/share/dbus-1/services"

test -x "$DISPATCH" || {
  echo "Missing dispatcher: $DISPATCH"
  exit 1
}

mkdir -p "$SERVICE_DIR"

write_service() {
  local name="$1"
  local path="${SERVICE_DIR}/${name}.service"

  cat > "$path" <<EOF
[D-BUS Service]
Name=${name}
Exec=${DISPATCH} --gapplication-service
EOF

  echo "  $path"
}

echo "Installed file-manager activation:"

# org.gnome.Nautilus is the app itself; org.freedesktop.FileManager1 is the
# standard "show this file in the file manager" API other apps call.
write_service org.gnome.Nautilus
write_service org.freedesktop.FileManager1

echo
echo "Dispatcher: $DISPATCH"
echo "Stock Nautilus remains installed and is still used outside Adaptive Desktop."
