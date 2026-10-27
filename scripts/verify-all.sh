#!/usr/bin/env bash
#
# Every check that needs no physical machine, in one run.
#
#   scripts/verify-all.sh           everything, including the four sandboxes
#   scripts/verify-all.sh --quick   skip the sandboxes (about five seconds)
#
# The sandboxes open real windows and a real GNOME Shell on a virtual display
# with a throwaway HOME, so none of this touches the desktop you are using.
# This is what .github/workflows/checks.yml runs. What still needs a person at
# the machine is listed by scripts/record-live-verification.py.
set -Euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SHELL_DIR="$REPO/shell/adaptive-shell@local"
QUICK=0
[ "${1:-}" = "--quick" ] && QUICK=1

failed=()
step() {
    local name="$1"; shift
    printf '== %s\n' "$name"
    if "$@"; then
        printf '   passed\n\n'
    else
        printf '   FAILED\n\n'
        failed+=("$name")
    fi
}
quiet() { "$@" >/tmp/adaptive-verify.$$ 2>&1 || { tail -40 /tmp/adaptive-verify.$$; rm -f /tmp/adaptive-verify.$$; return 1; }; rm -f /tmp/adaptive-verify.$$; }

shell_syntax() {
    local module
    for module in "$SHELL_DIR"/*.js "$REPO/scripts/nested-probe"/*/extension.js; do
        node --check "$module" || return 1
    done
}

shell_methods() {
    local standalone=()
    local module
    for module in "$SHELL_DIR"/*.js; do
        case "$(basename "$module")" in
            # Parts of the one shell class are checked together, below.
            extension.js|shellLock.js|shellDock*.js|shellDisplays.js) ;;
            controlCenter.js|ccNetwork.js|ccBluetooth.js|ccMedia.js|ccSystem.js) ;;
            *) standalone+=("$module") ;;
        esac
    done
    python3 "$REPO/scripts/verify-shell-methods.py" "${standalone[@]}" &&
        python3 "$REPO/scripts/verify-shell-methods.py" --class \
            "$SHELL_DIR"/{extension,shellLock,shellDock,shellDockFeatures,shellDockDnd,shellDockAutohide,shellDisplays}.js &&
        python3 "$REPO/scripts/verify-shell-methods.py" --class \
            "$SHELL_DIR"/{controlCenter,ccNetwork,ccBluetooth,ccMedia,ccSystem}.js
}

undefined_names() {
    # A name used but never defined loads fine in GJS and fails when reached.
    # ESLint's no-undef finds it; it is used if it is installed, otherwise
    # through npx when the network allows, otherwise skipped.
    local eslint
    if command -v eslint >/dev/null; then
        eslint=(eslint)
    elif command -v npx >/dev/null && npx --yes eslint@8 --version >/dev/null 2>&1; then
        eslint=(npx --yes eslint@8)
    else
        echo "   skipped: eslint is not available"
        return 0
    fi
    "${eslint[@]}" --no-eslintrc -c "$REPO/config/eslint-shell.json" --quiet "$SHELL_DIR"/*.js
}

python_syntax() {
    local file
    while IFS= read -r file; do
        python3 -m py_compile "$file" || return 1
    done < <(git -C "$REPO" ls-files -co --exclude-standard '*.py' | grep -vE '^(\.local|vendor|build)/' | sed "s|^|$REPO/|")
}

shell_scripts() {
    command -v shellcheck >/dev/null || { echo "   skipped: shellcheck is not installed"; return 0; }
    # Errors only: the older scripts carry style warnings that are not defects.
    shellcheck -S error "$REPO"/install.sh "$REPO"/uninstall.sh "$REPO"/scripts/*.sh
}

step "Shell modules parse" shell_syntax
step "Every this._method() is defined" quiet shell_methods
step "What one shell module takes from another is exported" quiet python3 "$REPO/scripts/verify-shell-imports.py" "$SHELL_DIR"
step "No undefined names in the shell" undefined_names
step "Shell helpers (git, watchdog, battery, clipboard, drop-down)" quiet node "$REPO/scripts/verify-shell-helpers.js"
step "Screen text geometry and selection" quiet node "$REPO/scripts/verify-screen-text.js"
step "Notification order (urgent, then newest)" quiet node "$REPO/scripts/verify-notification-order.js"
step "ROS 2 New package dialog logic" quiet node "$REPO/scripts/verify-ros-package-model.js"
step "Dynamic Island providers (usage, tasks, music, focus)" quiet node "$REPO/scripts/verify-dynamic-island.js"
step "Dynamic Island cards and Activity Center" quiet node "$REPO/scripts/verify-island-frontend.js"
step "Screen text contrast and enlargement" quiet /usr/bin/python3 -s "$REPO/scripts/verify-screen-text-image.py"
step "Python parses" python_syntax
step "Shell scripts have no errors" shell_scripts
step "Zero-State Protocol guards" quiet "$REPO/scripts/verify-zero-state-protocol.sh"
step "The checkout works from any folder, for any user" quiet "$REPO/scripts/verify-portable-paths.sh"
step "Feature logic (palette, projects, backup, power, annotate)" quiet python3 "$REPO/scripts/verify-feature-logic.py"
step "Terminal routes and ROS shell setup" quiet python3 "$REPO/scripts/verify-terminal.py"
step "agy, claude and codex as apps: shared sessions" quiet python3 "$REPO/scripts/verify-agent-apps.py"
step "Phone: phone choice, its apps, scrcpy arguments" quiet python3 "$REPO/scripts/verify-phone.py"
step "Adaptive Settings backend" quiet python3 "$REPO/scripts/verify-adaptive-settings.py"
step "Cast: Miracast elements, RTSP framing, format choice" quiet python3 "$REPO/scripts/verify-cast.py"
step "Agent Office (syntax, roster, API guards; no quota)" quiet "$REPO/scripts/verify-agent-office.sh"

inspector_static() {
    python3 - "$REPO" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("inspector_check", sys.argv[1] + "/scripts/verify-files-inspector.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
sys.exit(0 if module.controller_calls() else 1)
PY
}
step "Files inspector: every method the controller calls is defined" quiet inspector_static

if [ "$QUICK" = 0 ]; then
    step "Command palette window (virtual display)" quiet python3 "$REPO/scripts/verify-palette.py"
    step "Annotate window (virtual display)" quiet python3 "$REPO/scripts/verify-annotate.py"
    step "Extension in a real GNOME Shell (nested, sandboxed)" quiet "$REPO/scripts/verify-shell-nested.sh" --extra "$REPO/scripts/verify-screen-text-nested.sh" --extra "$REPO/scripts/verify-ros-nested.sh"
    step "ROS 2 panel helper against real nodes (private domain; skips without ROS 2)" quiet python3 "$REPO/scripts/verify-ros-panel.py"
    step "ROS 2 New package: every template created, built and run (skips without ROS 2)" quiet python3 "$REPO/scripts/verify-ros-package-create.py"
    step "Files with the inspector (the Nautilus fork, sandboxed)" quiet python3 "$REPO/scripts/verify-files-inspector.py"
    step "Adaptive Link: the daemon against a phone and three intruders" quiet python3 "$REPO/scripts/verify-link.py"
    step "Adaptive Link: the Android app on a device (skips with none attached)" quiet python3 "$REPO/scripts/verify-link-android.py"
fi

if [ "${#failed[@]}" != 0 ]; then
    echo "${#failed[@]} check(s) failed:"
    printf '  %s\n' "${failed[@]}"
    exit 1
fi
echo "All checks passed."
