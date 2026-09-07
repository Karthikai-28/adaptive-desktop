#!/usr/bin/env bash
set -Eeuo pipefail
export SETUPTOOLS_USE_DISTUTILS=stdlib

unset PYTHONPATH || true
unset CMAKE_PREFIX_PATH || true
unset AMENT_PREFIX_PATH || true
unset COLCON_PREFIX_PATH || true
unset LD_LIBRARY_PATH || true

REPO="${HOME}/adaptive-desktop"
BUILD="${REPO}/build/adaptive-nautilus"

if [ ! -f "${BUILD}/build.ninja" ]; then
  echo "Run ./scripts/build-nautilus-fork.sh first."
  exit 1
fi

ninja -C "$BUILD" install

# Re-link the system extensions the fork cannot see on its own (Open in
# Terminal lives there). ninja install does not remove them, but a fresh
# prefix would have none, so run it every time.
"$(dirname "$0")/install-nautilus-fork-extensions.sh"

echo
echo "Installed only into:"
echo "  ${REPO}/.local/adaptive-nautilus"
echo
echo "System Nautilus remains installed."
