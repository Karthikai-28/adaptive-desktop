#!/usr/bin/env bash
# Build the patched libfprint for the Validity VFS7552 (138a:0091) reader.
#
#   fingerprint/build-driver.sh            build + tests -> .local/fingerprint-driver/stage
#   fingerprint/build-driver.sh --no-test  skip the test run
#
# Official libfprint v1.94.100 (checksum-pinned) + libfprint-vfs7552-pattern.patch.
# Nothing is installed system-wide and nothing needs root: Ubuntu 22.04's meson
# is too old (libfprint needs >= 0.62), so meson lives in a local venv, and the
# GUsb/umockdev development files are unpacked from Ubuntu's own .debs.
# scripts/install-fingerprint-driver.sh installs the result. docs/FINGERPRINT.md.
set -Eeuo pipefail
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../scripts/adaptive-paths.sh"

VERSION=v1.94.100
COMMIT=80a4b5ec612892c5c056c48dddaa561452cf37ec
SHA256=cd0997590f510d58f60ae560bda5f131fbea050a729bfd0f0a4cc8417be23170
URL="https://gitlab.freedesktop.org/api/v4/projects/libfprint%2Flibfprint/repository/archive.tar.gz?sha=$COMMIT"
PATCH="$ADAPTIVE_REPO/fingerprint/libfprint-vfs7552-pattern.patch"
WORK="$ADAPTIVE_REPO/.local/fingerprint-driver"
RESEARCH="$ADAPTIVE_REPO/.local/fingerprint-research"   # earlier downloads, reused when present
SRC="$WORK/libfprint-$VERSION"
BUILD="$WORK/build"
STAGE="$WORK/stage"
DEPS="$WORK/deps"
TEST=1

case "${1:-}" in
    --no-test) TEST=0 ;;
    --help|-h) sed -n '2,11p' "$0"; exit 0 ;;
    '') ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
esac
mkdir -p "$WORK"
step() { printf '\n== %s\n' "$*"; }

step "Upstream source $VERSION"
tarball="$WORK/libfprint-$VERSION.tar.gz"
if [ ! -f "$tarball" ] && [ -f "$RESEARCH/source.tar.gz" ]; then
    cp "$RESEARCH/source.tar.gz" "$tarball"
fi
[ -f "$tarball" ] || curl -fL --retry 3 -o "$tarball" "$URL"
echo "$SHA256  $tarball" | sha256sum -c --quiet - || { echo "Checksum mismatch: $tarball" >&2; exit 1; }
rm -rf "$SRC"
mkdir -p "$SRC"
tar -xzf "$tarball" -C "$SRC" --strip-components=1
# The source sits inside the Adaptive checkout (.local/), where a plain
# `git apply` resolves paths against the outer repository and silently skips
# every file. A repository of its own makes the patch apply here.
git -C "$SRC" init -q
git -C "$SRC" apply --whitespace=nowarn "$PATCH"
for f in libfprint/fpi-pattern.cpp libfprint/fpi-pattern-print.c libfprint/drivers/vfs7552_image.h; do
    [ -f "$SRC/$f" ] || { echo "Patch did not apply: $f missing" >&2; exit 1; }
done
grep -q 'pattern_threshold = VFS7552_PATTERN_THRESHOLD' "$SRC/libfprint/drivers/vfs7552.c" || {
    echo "Patch did not apply to the VFS7552 driver" >&2; exit 1; }
echo "patched with $(basename "$PATCH")"

step "Build tools"
if [ ! -x "$WORK/venv/bin/meson" ]; then
    python3 -m venv "$WORK/venv"
    "$WORK/venv/bin/pip" install --quiet 'meson==1.3.2'
fi
if [ ! -f "$DEPS/usr/lib/x86_64-linux-gnu/pkgconfig/gusb.pc" ]; then
    mkdir -p "$DEPS/debs"
    if ls "$RESEARCH"/packages/*.deb >/dev/null 2>&1; then
        cp "$RESEARCH"/packages/*.deb "$DEPS/debs/"
    else
        (cd "$DEPS/debs" && apt-get download libgusb-dev gir1.2-gusb-1.0 libgusb2 \
            umockdev libumockdev0 gir1.2-umockdev-1.0)
    fi
    for deb in "$DEPS"/debs/*.deb; do dpkg-deb -x "$deb" "$DEPS"; done
    # Point the unpacked .pc files at the unpacked tree.
    sed -i "s|^prefix=/usr|prefix=$DEPS/usr|" "$DEPS"/usr/lib/x86_64-linux-gnu/pkgconfig/*.pc
fi
for lib in opencv_core opencv_imgproc opencv_features2d opencv_calib3d; do
    [ -e "/usr/lib/x86_64-linux-gnu/lib$lib.so" ] || {
        echo "Missing lib$lib.so: sudo apt install libopencv-dev" >&2; exit 1; }
done

export CCACHE_DISABLE=1
export PKG_CONFIG_PATH="$DEPS/usr/lib/x86_64-linux-gnu/pkgconfig"
export XDG_DATA_DIRS="$DEPS/usr/share:/usr/share"
export GI_TYPELIB_PATH="$DEPS/usr/lib/x86_64-linux-gnu/girepository-1.0"
export LD_LIBRARY_PATH="$DEPS/usr/lib/x86_64-linux-gnu"
export PATH="$DEPS/usr/bin:$PATH"

step "Configure and build"
rm -rf "$BUILD" "$STAGE"
"$WORK/venv/bin/meson" setup "$BUILD" "$SRC" --prefix=/usr --libdir=lib \
    -Ddrivers=vfs7552,virtual_image -Ddoc=false -Dintrospection=true \
    -Dgtk-examples=false -Dinstalled-tests=false \
    -Dudev_rules=disabled -Dudev_hwdb=disabled -Dbuildtype=release >"$WORK/configure.log"
ninja -C "$BUILD" >"$WORK/build.log" || { tail -30 "$WORK/build.log" >&2; exit 1; }

if [ "$TEST" = 1 ]; then
    step "Tests (VFS7552 replay, virtual image reader, unit tests)"
    "$WORK/venv/bin/meson" test -C "$BUILD" --print-errorlogs \
        vfs7552 fpi-ssm fpi-assembling fp-context fpi-device fp-device \
        VirtualImage.test_enroll_verify VirtualImage.test_identify \
        VirtualImage.test_verify_serialized VirtualImage.test_features \
        VirtualImage.test_capture_prevents_close | grep -E '^ *[0-9]+/|^(Ok|Fail):'
fi

step "Stage"
DESTDIR="$STAGE" "$WORK/venv/bin/meson" install -C "$BUILD" --no-rebuild --quiet
lib="$STAGE/usr/lib/libfprint-2.so.2.0.0"
[ -f "$lib" ] || { echo "No staged library at $lib" >&2; exit 1; }
if LC_ALL=C readelf -d "$lib" | grep -Eq 'RPATH|RUNPATH'; then
    echo "Staged library still has a build search path" >&2; exit 1
fi
LC_ALL=C readelf -d "$lib" | grep -Fq 'Library soname: [libfprint-2.so.2]' || {
    echo "Staged library has an unexpected soname" >&2; exit 1; }
nm -D --defined-only "$lib" >/dev/null 2>&1 || true
grep -q 'Too little ridge texture' "$lib" || {
    echo "Staged library does not contain the pattern matcher" >&2; exit 1; }
install -m 0644 "$lib" "$WORK/libfprint-2.so.2"
sha256sum "$WORK/libfprint-2.so.2" | tee "$WORK/libfprint-2.so.2.sha256"
echo "Built. Install with: scripts/install-fingerprint-driver.sh"
