#!/usr/bin/env bash
set -Eeuo pipefail

# Install Phone: the paired Android phone, and each of its apps, in windows
# on this computer (apps/adaptive-phone, scrcpy over adb).
#
#   app       "Phone" in the app grid; the palette's "phone" mode opens one app
#   command   adaptive-phone [--screen-off | app NAME | apps]
#
# scrcpy is pinned and checked against its published SHA-256, then kept in
# .local/scrcpy (not tracked). adb is the repository SDK's or the system's.
# On the phone, once: Developer options, Wireless debugging, pair this
# computer (or USB debugging and a cable).

. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/adaptive-paths.sh"
REPO="$ADAPTIVE_REPO"
APPS="$HOME/.local/share/applications"
DESKTOP="adaptive-phone.desktop"
VERSION="4.1"
SHA256="ad56ae8bfeedf41e824945c11dbf55fcb092b3e615b9b486f48a50e30d389635"
NAME="scrcpy-linux-x86_64-v$VERSION"
TARGET="$REPO/.local/scrcpy"
CACHE="$REPO/.local/scrcpy-dl"

if [ "$(cat "$TARGET/VERSION" 2>/dev/null)" != "$VERSION" ]; then
    mkdir -p "$CACHE"
    archive="$CACHE/$NAME.tar.gz"
    if ! echo "$SHA256  $archive" | sha256sum -c --status 2>/dev/null; then
        echo "Downloading scrcpy $VERSION"
        curl -fL --retry 3 -o "$archive.part" "https://github.com/Genymobile/scrcpy/releases/download/v$VERSION/$NAME.tar.gz"
        mv "$archive.part" "$archive"
    fi
    echo "$SHA256  $archive" | sha256sum -c --status || { echo "scrcpy $VERSION does not match its published checksum" >&2; exit 1; }
    unpacked="$(mktemp -d "$CACHE/unpack.XXXXXX")"
    tar -xzf "$archive" -C "$unpacked"
    rm -rf "$TARGET"
    mv "$unpacked/$NAME" "$TARGET"
    rmdir "$unpacked"
    echo "$VERSION" > "$TARGET/VERSION"
fi

mkdir -p "$APPS" "$HOME/.local/bin"
chmod +x "$REPO/apps/adaptive-phone/phone.py"
adaptive_render "$REPO/apps/adaptive-phone/$DESKTOP" "$APPS/$DESKTOP"
ln -sfn "$REPO/apps/adaptive-phone/phone.py" "$HOME/.local/bin/adaptive-phone"
update-desktop-database "$APPS" 2>/dev/null || true

echo "Installed:"
echo "  $APPS/$DESKTOP"
echo "  $HOME/.local/bin/adaptive-phone -> apps/adaptive-phone/phone.py"
echo "  scrcpy $VERSION in .local/scrcpy"
if [ ! -x "$REPO/.local/android-sdk/platform-tools/adb" ] && ! command -v adb >/dev/null; then
    echo "Phone needs adb: sudo apt install adb"
fi
