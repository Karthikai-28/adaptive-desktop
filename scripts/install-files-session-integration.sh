#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${ADAPTIVE_REPO:-$HOME/adaptive-desktop}"
DISPATCH="$REPO/scripts/adaptive-files-dispatch.sh"

APP_DIR="$HOME/.local/share/applications"
DESKTOP="$APP_DIR/org.gnome.Nautilus.desktop"
LEGACY_DESKTOP="$APP_DIR/com.karthi.AdaptiveFiles.desktop"

SERVICE_DIR="$HOME/.local/share/dbus-1/services"

test -x "$DISPATCH" || {
    echo "Missing dispatcher: $DISPATCH" >&2
    exit 1
}

mkdir -p "$APP_DIR" "$SERVICE_DIR"

write_service() {
    local name="$1"
    local path="$SERVICE_DIR/${name}.service"

    cat > "$path" <<EOF
[D-BUS Service]
Name=${name}
Exec=${DISPATCH} --gapplication-service
EOF

    chmod 0644 "$path"
}

write_service org.gnome.Nautilus
write_service org.freedesktop.FileManager1

# Visible standard desktop ID. This is deliberately the normal Nautilus ID:
# GNOME Shell, MIME handlers, favorites and FileManager1 all agree on one app.
# D-Bus activation still goes through the dispatcher above.
cat > "$DESKTOP" <<EOF
[Desktop Entry]
Name=Files
GenericName=File Manager
Comment=Browse and manage files
Keywords=folder;manager;explore;disk;filesystem;nautilus;
Exec=${DISPATCH} --new-window %U
Icon=org.gnome.Nautilus
Terminal=false
Type=Application
DBusActivatable=true
StartupNotify=true
NoDisplay=false
Hidden=false
Categories=GNOME;GTK;Utility;Core;FileManager;
MimeType=inode/directory;application/x-7z-compressed;application/x-7z-compressed-tar;application/x-bzip;application/x-bzip-compressed-tar;application/x-compress;application/x-compressed-tar;application/x-cpio;application/x-gzip;application/x-lha;application/x-lzip;application/x-lzip-compressed-tar;application/x-lzma;application/x-lzma-compressed-tar;application/x-tar;application/x-tarz;application/x-xz;application/x-xz-compressed-tar;application/zip;application/gzip;application/bzip2;application/vnd.rar;
X-GNOME-UsesNotifications=true
Actions=new-window;

[Desktop Action new-window]
Name=New Window
Exec=${DISPATCH} --new-window
EOF

chmod 0644 "$DESKTOP"

# The old duplicate app used the retired v1.6 launcher. Keeping both creates
# phantom/duplicate Files entries and can route to a missing executable.
if [[ -f "$LEGACY_DESKTOP" ]]; then
    if grep -q 'adaptive-files-launch-v1.6.sh' "$LEGACY_DESKTOP" \
        || grep -q '^Name=Adaptive Files$' "$LEGACY_DESKTOP"; then
        rm -f "$LEGACY_DESKTOP"
    fi
fi

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APP_DIR" >/dev/null 2>&1 || true
fi

xdg-mime default org.gnome.Nautilus.desktop inode/directory

# Push the current Adaptive session markers into the D-Bus activation
# environment when possible. The dispatcher also has a GNOME Shell
# /proc fallback, so reboot does not depend solely on this call.
if command -v dbus-update-activation-environment >/dev/null 2>&1; then
    dbus-update-activation-environment \
        DCONF_PROFILE \
        GDMSESSION \
        XDG_SESSION_DESKTOP \
        XDG_CURRENT_DESKTOP \
        XDG_SESSION_TYPE \
        >/dev/null 2>&1 || true
fi

echo "Installed:"
echo "  $DESKTOP"
echo "  $SERVICE_DIR/org.gnome.Nautilus.service"
echo "  $SERVICE_DIR/org.freedesktop.FileManager1.service"
