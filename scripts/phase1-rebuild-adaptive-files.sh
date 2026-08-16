#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
SOURCE_FILE="${REPO}/vendor/NAUTILUS_SOURCE_PATH"
SOURCE="$(cat "$SOURCE_FILE")"
BUILD="${REPO}/build/adaptive-nautilus"
PREFIX="${REPO}/.local/adaptive-nautilus"

export SETUPTOOLS_USE_DISTUTILS=stdlib

unset PYTHONPATH || true
unset CMAKE_PREFIX_PATH || true
unset AMENT_PREFIX_PATH || true
unset COLCON_PREFIX_PATH || true
unset LD_LIBRARY_PATH || true

echo "Source:"
echo "  $SOURCE"
echo "Build:"
echo "  $BUILD"
echo "Prefix:"
echo "  $PREFIX"
echo

rm -rf "$BUILD"

meson setup \
  "$BUILD" \
  "$SOURCE" \
  --prefix="$PREFIX" \
  --buildtype=debugoptimized \
  -Dlibportal=false

ninja -C "$BUILD"

ninja -C "$BUILD" install

echo
echo "Adaptive Files Phase 1 build/install completed."
echo "Run:"
echo "  ./scripts/phase1-run-adaptive-files.sh"
