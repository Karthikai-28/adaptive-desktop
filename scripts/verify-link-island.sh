#!/usr/bin/env bash
# Render and exercise the island on the dedicated test emulator only.
set -Eeuo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SDK="$REPO/.local/android-sdk"
APP="$REPO/apps/adaptive-link-android"
ADB="$SDK/platform-tools/adb"
SERIAL=emulator-5584
GRADLE="$(find "$HOME/.gradle/wrapper/dists/gradle-8.13-bin" -path '*/bin/gradle' -type f -print -quit)"
[ -x "$REPO/.local/jdk-17/bin/java" ] && export JAVA_HOME="$REPO/.local/jdk-17"
"$ADB" -s "$SERIAL" get-state >/dev/null
(cd "$APP" && ANDROID_HOME="$SDK" "$GRADLE" --no-daemon -q compileDebugKotlin compileDebugAndroidTestKotlin testDebugUnitTest lintDebug -Pabi=arm64-v8a,x86_64)
(cd "$APP" && ANDROID_HOME="$SDK" "$GRADLE" --no-daemon -q assembleDebug assembleDebugAndroidTest -Pabi=arm64-v8a,x86_64)
"$ADB" -s "$SERIAL" install -r "$APP/app/build/outputs/apk/debug/app-debug.apk"
"$ADB" -s "$SERIAL" install -r "$APP/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk"
"$ADB" -s "$SERIAL" shell input keyevent KEYCODE_WAKEUP
# The full app suite leaves this disposable emulator protected with its fixed test PIN.
timeout 5 "$ADB" -s "$SERIAL" shell wm dismiss-keyguard || true
"$ADB" -s "$SERIAL" shell input text 2580
"$ADB" -s "$SERIAL" shell input keyevent KEYCODE_ENTER
"$ADB" -s "$SERIAL" shell appops set com.karthi.adaptivelink SYSTEM_ALERT_WINDOW allow
trap '"$ADB" -s "$SERIAL" shell appops set com.karthi.adaptivelink SYSTEM_ALERT_WINDOW default >/dev/null' EXIT
result="$(timeout 180 "$ADB" -s "$SERIAL" shell am instrument -w -e class com.karthi.adaptivelink.IslandInstrumentedTest,com.karthi.adaptivelink.WidgetInstrumentedTest com.karthi.adaptivelink.test/androidx.test.runner.AndroidJUnitRunner)"
printf '%s\n' "$result"
[[ "$result" == *"OK (5 tests)"* ]]

mkdir -p "$REPO/logs/link-widget-previews"
"$ADB" -s "$SERIAL" pull /sdcard/Android/data/com.karthi.adaptivelink/files/widget-previews/. "$REPO/logs/link-widget-previews/"
