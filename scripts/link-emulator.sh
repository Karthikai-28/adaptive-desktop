#!/usr/bin/env bash
# Start (or stop) the headless Android emulator used to test the Adaptive
# Link app: scripts/verify-link-android.py runs against it.
#
#   link-emulator.sh          start it and wait until it has booted
#   link-emulator.sh --stop   shut it down
#
# The SDK, emulator and virtual phone live in .local/android-sdk (not tracked).
set -Eeuo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SDK="$REPO/.local/android-sdk"
export ANDROID_HOME="$SDK" ANDROID_SDK_ROOT="$SDK" ANDROID_AVD_HOME="$SDK/avd"
ADB="$SDK/platform-tools/adb"
SERIAL=emulator-5584

if [ ! -x "$SDK/emulator/emulator" ]; then
    echo "The Android emulator is not installed in $SDK (see docs/ADAPTIVE_LINK.md)." >&2
    exit 1
fi
if [ "${1:-}" = "--stop" ]; then
    "$ADB" -s "$SERIAL" emu kill >/dev/null 2>&1 || true
    echo "Emulator stopped."
    exit 0
fi
if [ "$("$ADB" -s "$SERIAL" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = 1 ]; then
    echo "Emulator already running ($SERIAL)."
    exit 0
fi
if [ ! -d "$ANDROID_AVD_HOME/link-test.avd" ]; then
    mkdir -p "$ANDROID_AVD_HOME"
    echo no | "$SDK/cmdline-tools/latest/bin/avdmanager" create avd -n link-test \
        -k "system-images;android-34;default;x86_64" -d pixel_5 --force >/dev/null
fi
nohup "$SDK/emulator/emulator" -avd link-test -no-window -no-audio -no-snapshot -no-boot-anim \
    -gpu swiftshader_indirect -port 5584 >"$ANDROID_AVD_HOME/emulator.log" 2>&1 &
for _ in $(seq 1 100); do
    [ "$("$ADB" -s "$SERIAL" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = 1 ] && break
    sleep 3
done
"$ADB" -s "$SERIAL" shell getprop sys.boot_completed | grep -q 1 && echo "Emulator booted ($SERIAL)."
