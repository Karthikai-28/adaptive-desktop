#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
VENDOR="${REPO}/vendor"
WORK="${VENDOR}/nautilus-ubuntu"

mkdir -p "$VENDOR"

if ! command -v nautilus >/dev/null 2>&1; then
  echo "System Nautilus is not installed."
  exit 1
fi

VERSION="$(dpkg-query -W -f='${Version}' nautilus)"
echo "Installed Ubuntu Nautilus: $VERSION"

if ! grep -RhsE '^[[:space:]]*deb-src[[:space:]]+' \
  /etc/apt/sources.list /etc/apt/sources.list.d 2>/dev/null | grep -q .
then
  echo
  echo "Ubuntu source repositories (deb-src) are not enabled."
  echo "Run ./scripts/check-source-repos.sh for details."
  exit 2
fi

rm -rf "$WORK"
mkdir -p "$WORK"
cd "$WORK"

echo
echo "Fetching Ubuntu's Nautilus source package..."
apt-get source "nautilus=${VERSION}" || apt-get source nautilus

SOURCE_DIR="$(find . -mindepth 1 -maxdepth 1 -type d -name 'nautilus-*' | head -1)"

if [ -z "$SOURCE_DIR" ]; then
  echo "Unable to locate extracted Nautilus source."
  exit 3
fi

SOURCE_DIR="$(realpath "$SOURCE_DIR")"

printf '%s\n' "$SOURCE_DIR" > "${REPO}/vendor/NAUTILUS_SOURCE_PATH"

echo
echo "Ubuntu Nautilus source ready:"
echo "  $SOURCE_DIR"
echo
echo "Stock Nautilus remains untouched."
