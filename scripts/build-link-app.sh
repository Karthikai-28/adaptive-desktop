#!/usr/bin/env bash
# Build the Adaptive Link Android app and put the APK in dist/.
#
#   build-link-app.sh             build dist/adaptive-link.apk
#   build-link-app.sh --install   also install it on the phone attached by USB
#
# Needs the Android SDK in .local/android-sdk and Gradle 8.13 (see
# docs/ADAPTIVE_LINK.md). The APK is signed with this machine's debug key,
# which is all a phone needs for an app you install yourself.
set -Eeuo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SDK="$REPO/.local/android-sdk"
APP="$REPO/apps/adaptive-link-android"

GRADLE="$(ls -d "$HOME"/.gradle/wrapper/dists/gradle-8.13-bin/*/gradle-8.13/bin/gradle 2>/dev/null | head -1 || true)"
[ -n "$GRADLE" ] || GRADLE="$(command -v gradle || true)"
if [ ! -d "$SDK/platforms" ] || [ -z "$GRADLE" ]; then
    echo "The Android SDK (.local/android-sdk) or Gradle is missing; see docs/ADAPTIVE_LINK.md." >&2
    exit 1
fi

printf 'sdk.dir=%s\n' "$SDK" >"$APP/local.properties"
(cd "$APP" && ANDROID_HOME="$SDK" "$GRADLE" --no-daemon -q clean assembleDebug testDebugUnitTest)
mkdir -p "$REPO/dist"
cp "$APP/app/build/outputs/apk/debug/app-debug.apk" "$REPO/dist/adaptive-link.apk"
echo "Built $REPO/dist/adaptive-link.apk ($(du -h "$REPO/dist/adaptive-link.apk" | cut -f1))"

if [ "${1:-}" = "--install" ]; then
    # A real phone, not the test emulator.
    serial="$("$SDK/platform-tools/adb" devices | awk 'NR>1 && $2=="device" && $1 !~ /^emulator-/ {print $1; exit}')"
    if [ -z "$serial" ]; then
        echo "No phone is attached. Turn on USB debugging, plug it in and accept the prompt on the phone." >&2
        exit 1
    fi
    "$SDK/platform-tools/adb" -s "$serial" install -r "$REPO/dist/adaptive-link.apk"
    echo "Installed on $serial."
fi
