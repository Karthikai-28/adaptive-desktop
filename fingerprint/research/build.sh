#!/usr/bin/env bash
# Build the measurement tools against a research libfprint (frame dump enabled).
# Needs fingerprint/build-driver.sh to have run once (patched source, meson, deps).
# Output stays in .local/fingerprint-driver/research; nothing is installed.
set -Eeuo pipefail
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../../scripts/adaptive-paths.sh"
WORK="$ADAPTIVE_REPO/.local/fingerprint-driver"
SRC="$WORK/libfprint-v1.94.100"; B="$WORK/research/build"; OUT="$WORK/research"; DEPS="$WORK/deps/usr"
HERE="$ADAPTIVE_REPO/fingerprint/research"
[ -d "$SRC" ] || { echo "Run fingerprint/build-driver.sh first." >&2; exit 1; }
export CCACHE_DISABLE=1 PKG_CONFIG_PATH="$DEPS/lib/x86_64-linux-gnu/pkgconfig" XDG_DATA_DIRS="$DEPS/share:/usr/share"
export GI_TYPELIB_PATH="$DEPS/lib/x86_64-linux-gnu/girepository-1.0" LD_LIBRARY_PATH="$DEPS/lib/x86_64-linux-gnu"
[ -d "$B" ] || "$WORK/venv/bin/meson" setup "$B" "$SRC" -Ddrivers=vfs7552,virtual_image -Ddoc=false \
    -Dintrospection=true -Dgtk-examples=false -Dinstalled-tests=false -Dudev_rules=disabled \
    -Dudev_hwdb=disabled -Dbuildtype=release -Dc_args=-DVFS7552_RESEARCH_DUMP >/dev/null
ninja -C "$B" >/dev/null
L="$SRC/libfprint"
CF="$(pkg-config --cflags glib-2.0 gio-2.0 gusb gobject-2.0) -I$L -I$B/libfprint -I$B -I$L/nbis/include -I$L/nbis/libfprint-include"
LIBS="$(pkg-config --libs glib-2.0 gio-2.0 gusb gobject-2.0 gmodule-2.0) -lusb-1.0 -lm -lpthread"
RP="-Wl,-rpath,$B/libfprint:$DEPS/lib/x86_64-linux-gnu"
gcc -O2 -o "$OUT/vfs-capture" "$HERE/vfs-capture.c" $CF -L"$B/libfprint" -lfprint-2 $RP $LIBS
gcc -O2 -Wno-deprecated-declarations -o "$OUT/vfs-score" "$HERE/vfs-score.c" $CF \
    "$B/libfprint/libfprint-private.a" "$B/libfprint/libnbis.a" -L"$B/libfprint" -lfprint-2 $RP $LIBS
g++ -x c -O2 -c -o "$OUT/pattern-check.o" "$HERE/pattern-check.c" $CF -I"$L/drivers" -Wno-unused-variable
g++ -O2 -o "$OUT/pattern-check" "$OUT/pattern-check.o" "$B/libfprint/libfprint-private.a" $LIBS \
    -lopencv_core -lopencv_imgproc -lopencv_features2d -lopencv_calib3d
echo "Tools in $OUT"
