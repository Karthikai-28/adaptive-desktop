#!/usr/bin/env bash
set -Eeuo pipefail
export SETUPTOOLS_USE_DISTUTILS=stdlib

unset PYTHONPATH || true
unset CMAKE_PREFIX_PATH || true
unset AMENT_PREFIX_PATH || true
unset COLCON_PREFIX_PATH || true
unset LD_LIBRARY_PATH || true

REPO="${HOME}/adaptive-desktop"
PATH_FILE="${REPO}/vendor/NAUTILUS_SOURCE_PATH"
PREFIX="${REPO}/.local/adaptive-nautilus"

if [ ! -f "$PATH_FILE" ]; then
  echo "Run ./scripts/prepare-nautilus-fork.sh first."
  exit 1
fi

SOURCE="$(cat "$PATH_FILE")"
BUILD="${REPO}/build/adaptive-nautilus"

rm -rf "$BUILD"
mkdir -p "$BUILD"

meson setup \
  "$BUILD" \
  "$SOURCE" \
  --prefix="$PREFIX" \
  --buildtype=debugoptimized \
  -Dlibportal=false

ninja -C "$BUILD"

echo
echo "Build completed."
echo "Nothing has been installed into /usr."
echo "Next:"
echo "  ./scripts/install-nautilus-fork-local.sh"
