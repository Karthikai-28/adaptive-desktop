#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
APP_DIR="${HOME}/.local/share/applications"
ICON_DIR="${HOME}/.local/share/icons/hicolor/scalable/apps"
CUSTOM="${APP_DIR}/com.karthi.AdaptiveFiles.desktop"
NAUTILUS_OVERRIDE="${APP_DIR}/org.gnome.Nautilus.desktop"

mkdir -p "$APP_DIR" "$ICON_DIR"

cat > "$CUSTOM" <<EOF
[Desktop Entry]
Type=Application
Name=Adaptive Files
Comment=Adaptive Desktop File Explorer
Exec=${REPO}/scripts/adaptive-files-launch-v1.6.sh
Icon=com.karthi.AdaptiveFiles
Terminal=false
Categories=System;FileManager;Utility;Core;
MimeType=inode/directory;
StartupNotify=true
DBusActivatable=false
EOF

# Per-user override only. /usr/share/applications/org.gnome.Nautilus.desktop
# remains untouched and can be restored simply by deleting this file.
cat > "$NAUTILUS_OVERRIDE" <<EOF
[Desktop Entry]
Type=Application
Name=Files
GenericName=File Manager
Comment=Open Adaptive Files
Exec=${REPO}/scripts/adaptive-files-launch-v1.6.sh
Icon=com.karthi.AdaptiveFiles
Terminal=false
Categories=GNOME;GTK;Utility;Core;FileManager;
MimeType=inode/directory;
StartupNotify=true
DBusActivatable=false
Actions=new-window;
X-GNOME-UsesNotifications=true;

[Desktop Action new-window]
Name=New Window
Exec=${REPO}/scripts/adaptive-files-launch-v1.6.sh
EOF

cp \
  "${REPO}/icons/AdaptiveFilesIcons/scalable/apps/com.karthi.AdaptiveFiles.svg" \
  "${ICON_DIR}/com.karthi.AdaptiveFiles.svg"

chmod 0644 \
  "$CUSTOM" \
  "$NAUTILUS_OVERRIDE" \
  "${ICON_DIR}/com.karthi.AdaptiveFiles.svg"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APP_DIR" >/dev/null 2>&1 || true
fi

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache \
    -f "${HOME}/.local/share/icons/hicolor" \
    >/dev/null 2>&1 || true
fi

# Route ordinary directory-open requests through the standard Nautilus desktop
# ID, which is now overridden per-user to Adaptive Files.
xdg-mime default org.gnome.Nautilus.desktop inode/directory

if command -v gio >/dev/null 2>&1; then
  gio mime inode/directory org.gnome.Nautilus.desktop >/dev/null 2>&1 || true
fi

echo "Installed Adaptive Files routing:"
echo "  $CUSTOM"
echo "  $NAUTILUS_OVERRIDE"
echo
echo "Directory handler:"
xdg-mime query default inode/directory || true
