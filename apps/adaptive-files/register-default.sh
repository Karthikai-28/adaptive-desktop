#!/usr/bin/env bash
set -Eeuo pipefail

DESKTOP="com.karthi.AdaptiveFiles.desktop"

command -v xdg-mime >/dev/null || {
  echo "xdg-mime is required (package: xdg-utils)"
  exit 1
}

xdg-mime default "$DESKTOP" inode/directory

echo
echo "Current directory handler:"
xdg-mime query default inode/directory
echo
echo "This makes xdg-open and desktop integrations open folders in Adaptive Files."
echo "It does NOT replace GTK/portal file-picker dialogs embedded inside apps."
