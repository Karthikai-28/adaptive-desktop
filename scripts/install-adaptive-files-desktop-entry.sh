#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
APP_DIR="${HOME}/.local/share/applications"
ICON_DIR="${HOME}/.local/share/icons/hicolor/scalable/apps"
DESKTOP_FILE="${APP_DIR}/com.karthi.AdaptiveFiles.desktop"

mkdir -p "$APP_DIR" "$ICON_DIR"

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Adaptive Files
Comment=Adaptive Desktop File Explorer
Exec=${REPO}/scripts/adaptive-files-launch.sh
Icon=com.karthi.AdaptiveFiles
Terminal=false
Categories=System;FileManager;Utility;Core;
MimeType=inode/directory;
StartupNotify=true
DBusActivatable=false
EOF

cp \
  "${REPO}/icons/AdaptiveFilesIcons/scalable/apps/com.karthi.AdaptiveFiles.svg" \
  "${ICON_DIR}/com.karthi.AdaptiveFiles.svg"

chmod 0644 "$DESKTOP_FILE" "${ICON_DIR}/com.karthi.AdaptiveFiles.svg"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APP_DIR" >/dev/null 2>&1 || true
fi

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f "${HOME}/.local/share/icons/hicolor" >/dev/null 2>&1 || true
fi

echo "Installed:"
echo "  $DESKTOP_FILE"
echo "  ${ICON_DIR}/com.karthi.AdaptiveFiles.svg"
