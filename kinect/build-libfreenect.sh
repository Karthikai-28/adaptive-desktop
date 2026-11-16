#!/usr/bin/env bash
# Build libfreenect (the open driver for the Kinect v1, "Kinect for Xbox 360") for Air.
#
#   kinect/build-libfreenect.sh          build -> .local/libfreenect (lib/libfreenect{,_sync}.so)
#   kinect/build-libfreenect.sh --force  rebuild even when the libraries are already there
#
# Official libfreenect v0.7.5, checksum-pinned. Nothing is installed system-wide and nothing
# needs root: Air loads the two libraries from .local/libfreenect with ctypes
# (services/adaptive-air/kinect.py). Only the C core and the C "sync" wrapper are built: no
# examples, no Python/Cython wrapper, no OpenNI2 driver, no audio firmware download.
# Needs cmake, gcc and libusb-1.0-0-dev (apt). docs/AIR.md.
set -Eeuo pipefail
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../scripts/adaptive-paths.sh"

VERSION=0.7.5
SHA256=3c668053db726206a8c3a92e92e91ef7a64407968f422b9c4b828d0fd234c866
URL="https://github.com/OpenKinect/libfreenect/archive/refs/tags/v$VERSION.tar.gz"
WORK="$ADAPTIVE_REPO/.local/libfreenect-build"
PREFIX="$ADAPTIVE_REPO/.local/libfreenect"
FORCE=0

case "${1:-}" in
    --force) FORCE=1 ;;
    --help|-h) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    '') ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
esac

if [ "$FORCE" = 0 ] && [ -f "$PREFIX/lib/libfreenect_sync.so" ] && [ -f "$PREFIX/VERSION" ] \
        && [ "$(cat "$PREFIX/VERSION")" = "$VERSION" ]; then
    echo "libfreenect $VERSION already built in $PREFIX"
    exit 0
fi

for tool in cmake gcc pkg-config curl; do
    command -v "$tool" >/dev/null || { echo "missing: $tool (apt install $tool)" >&2; exit 1; }
done
pkg-config --exists libusb-1.0 || { echo "missing: libusb-1.0-0-dev (apt)" >&2; exit 1; }

mkdir -p "$WORK"
tarball="$WORK/libfreenect-$VERSION.tar.gz"
if [ ! -f "$tarball" ]; then
    echo "== downloading libfreenect $VERSION"
    curl -fsSL -o "$tarball.part" "$URL"
    mv "$tarball.part" "$tarball"
fi
echo "$SHA256  $tarball" | sha256sum -c --quiet - || {
    echo "checksum mismatch for $tarball; deleting it" >&2; rm -f "$tarball"; exit 1; }

rm -rf "$WORK/src" "$WORK/build"
mkdir -p "$WORK/src"
tar xzf "$tarball" -C "$WORK/src" --strip-components=1

echo "== building"
cmake -S "$WORK/src" -B "$WORK/build" -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$PREFIX" -DCMAKE_INSTALL_LIBDIR=lib \
    -DBUILD_EXAMPLES=OFF -DBUILD_FAKENECT=OFF -DBUILD_C_SYNC=ON -DBUILD_CPP=OFF \
    -DBUILD_REDIST_PACKAGE=ON -DBUILD_PYTHON=OFF -DBUILD_PYTHON3=OFF \
    -DBUILD_OPENNI2_DRIVER=OFF >"$WORK/cmake.log" 2>&1 || { tail -20 "$WORK/cmake.log"; exit 1; }
cmake --build "$WORK/build" -j"$(nproc)" >"$WORK/build.log" 2>&1 || { tail -30 "$WORK/build.log"; exit 1; }
rm -rf "$PREFIX"
cmake --install "$WORK/build" >"$WORK/install.log" 2>&1 || { tail -20 "$WORK/install.log"; exit 1; }
echo "$VERSION" >"$PREFIX/VERSION"
echo "libfreenect $VERSION -> $PREFIX/lib"
