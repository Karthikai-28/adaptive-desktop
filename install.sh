#!/usr/bin/env bash
#
# Install Adaptive Desktop for this user - one command instead of a dozen.
#
#   ./install.sh              install or update everything that needs no sudo
#   ./install.sh --status     say what is installed and what is out of date;
#                             changes nothing
#   ./install.sh --session    also install the login session (asks for sudo)
#   ./install.sh --only NAME  one part (see --list)
#   ./install.sh --list       the parts, in the order they run
#
# Each part is one of the scripts in scripts/, which stay usable on their own;
# this only runs them in the right order and reports. It never restarts your
# shell: the last line says what to do for the shell changes to take effect.
#
# The other direction is ./uninstall.sh. Ubuntu's own session is never
# touched by either.
set -Euo pipefail

. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/scripts/adaptive-paths.sh"
REPO="$ADAPTIVE_REPO"
S="$REPO/scripts"
UUID="adaptive-shell@local"
LIVE="$HOME/.local/share/gnome-shell/extensions/$UUID"
UNITS="$HOME/.config/systemd/user"
APPS="$HOME/.local/share/applications"

MODE=install
ONLY=""
SESSION=0
while [ $# -gt 0 ]; do
    case "$1" in
        --status) MODE=status ;;
        --list) MODE=list ;;
        --session) SESSION=1 ;;
        --only) ONLY="${2:-}"; shift ;;
        -h|--help) sed -n '3,17p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
    esac
    shift
done

# name | what it is | status check | install command
# A status check prints nothing and succeeds when the part is in place.
PARTS=(
    "project-service|Project Context Service (autostart, overview search)|status_project_service|$S/install-project-context-service.sh"
    "theme|Adaptive theme, icons, fonts and backgrounds|status_theme|$S/install-adaptive-theme.sh"
    "shell|Shell extension copied to its live folder|status_shell|$S/sync-shell.sh"
    "keybindings|Adaptive keyboard shortcuts|status_keybindings|$S/install-keybindings.sh"
    "terminal|Terminal defaults and KTERM integration|status_terminal|install_terminal"
    "settings|Adaptive Settings app|status_settings|$S/install-adaptive-settings.sh"
    "cast|Cast: this screen on a TV over Miracast|status_cast|$S/install-cast.sh"
    "phone|Phone: the paired Android phone and its apps in windows here (scrcpy)|status_phone|$S/install-phone.sh"
    "gestures|Touchpad gesture service|status_gestures|$S/install-gestures.sh"
    "files|Files inspector for the Nautilus fork|status_files|install_files"
    "wallpaper|Hourly wallpaper rotation|status_unit adaptive-wallpaper.timer|$S/install-wallpaper-rotation.sh"
    "file-index|Fifteen-minute home index for the palette|status_unit adaptive-index.timer|$S/install-file-index.sh"
    "power|Power profile follows the charger (only if you turned it on)|status_power|install_power"
    "link|Adaptive Link: this computer from your paired phone|status_unit adaptive-link.service|$S/install-link.sh"
    "agent-office|Agent Office: Gemini agents managed by Claude (127.0.0.1:8790)|status_agent_office|$S/install-agent-office.sh"
)

status_project_service() {
    [ -f "$HOME/.config/autostart/adaptive-project-context.desktop" ] || echo "not set to start at login"
}

status_theme() {
    [ -d "$HOME/.local/share/themes/Adaptive" ] || { echo "theme not installed"; return; }
    cmp -s "$REPO/theme/Adaptive/gtk-3.0/gtk.css" "$HOME/.local/share/themes/Adaptive/gtk-3.0/gtk.css" \
        || echo "installed theme is older than the repo's"
}

status_shell() {
    [ -d "$LIVE" ] || { echo "extension not installed"; return; }
    if ! diff -rq -x __pycache__ "$REPO/shell/$UUID" "$LIVE" >/dev/null 2>&1; then
        echo "live extension differs from the repo ($(diff -rq -x __pycache__ "$REPO/shell/$UUID" "$LIVE" 2>/dev/null | wc -l) file(s))"
    fi
}

status_keybindings() {
    local have missing=0 name
    have="$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings 2>/dev/null)"
    for name in $(sed -n 's/^set_binding "\(adaptive-[a-z-]*\)".*/\1/p' "$S/install-keybindings.sh"); do
        [[ "$have" == *"/$name/"* ]] || missing=$((missing + 1))
    done
    [ "$missing" = 0 ] || echo "$missing shortcut(s) not installed"
}

status_cast() {
    [ -f "$APPS/com.karthi.AdaptiveCast.desktop" ] || echo "not in the app grid"
}

status_phone() {
    [ -f "$APPS/adaptive-phone.desktop" ] || { echo "not in the app grid"; return; }
    [ -x "$REPO/.local/scrcpy/scrcpy" ] || echo "scrcpy is not in .local/scrcpy"
}

status_settings() {
    [ -f "$APPS/com.karthi.AdaptiveSettings.desktop" ] || echo "not in the app grid"
}

status_terminal() {
    [ -f "$HOME/.config/karthi-shell/terminator-modern.conf" ] || { echo "KTERM is not installed"; return; }
    cmp -s "$REPO/terminal/launcher.py" "$HOME/.local/bin/kterm-terminal" || echo "terminal routes need updating"
    grep -qx 'Name=Terminal' "$APPS/kterm-terminal.desktop" 2>/dev/null || echo "terminal name needs updating"
}

install_terminal() {
    if [ ! -f "$HOME/.config/karthi-shell/terminator-modern.conf" ]; then
        echo "KTERM is not installed; run terminal/install-kterm-ubuntu.sh first."
        return 0
    fi
    python3 "$S/install-terminal.py" --apply
}

status_gestures() {
    [ -f "$HOME/.config/autostart/adaptive-gestures.desktop" ] || echo "not set to start at login"
}

status_files() {
    [ -x "$REPO/.local/adaptive-nautilus/bin/nautilus" ] || { echo "skipped: the Nautilus fork is not built"; return; }
    # The build has its folder compiled in, so a checkout that moved needs it rebuilt.
    grep -qaF "$REPO/.local/adaptive-nautilus" "$REPO/.local/adaptive-nautilus/bin/nautilus" ||
        { echo "the Files fork was built in another folder: ./bootstrap.sh --only files-fork --redo"; return; }
    local installed="$REPO/.local/adaptive-nautilus/share/nautilus-python/extensions"
    [ -f "$installed/adaptive_preview.py" ] || { echo "inspector not installed in the fork"; return; }
    # The inspector is adaptive_preview.py and the package beside it.
    if ! cmp -s "$REPO/extension/adaptive_preview.py" "$installed/adaptive_preview.py" ||
        ! diff -rq -x __pycache__ "$REPO/extension/adaptive_files" "$installed/adaptive_files" >/dev/null 2>&1; then
        echo "installed inspector differs from the repo's"
    fi
}

install_files() {
    if [ ! -x "$REPO/.local/adaptive-nautilus/bin/nautilus" ]; then
        echo "The Nautilus fork is not built; skipping (scripts/build-nautilus-fork.sh builds it)."
        return 0
    fi
    "$S/install-files-extension.sh"
}

status_unit() {
    [ -f "$UNITS/$1" ] || { echo "not installed"; return; }
    systemctl --user is-enabled --quiet "$1" 2>/dev/null || echo "installed but not enabled"
}

status_agent_office() {
    # Starting at login is optional here (--autostart), so installed and running is enough.
    [ -f "$UNITS/adaptive-agent-office.service" ] || { echo "not installed"; return; }
    systemctl --user is-active --quiet adaptive-agent-office.service || echo "installed but not running"
}

power_wanted() {
    grep -q '"auto_profile": *true' "$HOME/.config/adaptive-desktop/power.json" 2>/dev/null
}

status_power() {
    if ! power_wanted; then
        # Off is a valid choice, not something to fix.
        return 0
    fi
    status_unit adaptive-power-auto.service
}

install_power() {
    if ! power_wanted; then
        echo "Automatic power profile is off (turn it on with scripts/adaptive-power-auto.py --enable)."
        return 0
    fi
    mkdir -p "$UNITS"
    adaptive_render "$REPO/services/adaptive-power-auto.service" "$UNITS/adaptive-power-auto.service"
    systemctl --user daemon-reload
    systemctl --user enable --now adaptive-power-auto.service
}

if [ "$MODE" = list ]; then
    for part in "${PARTS[@]}"; do
        IFS='|' read -r name what _ _ <<<"$part"
        printf '  %-16s %s\n' "$name" "$what"
    done
    exit 0
fi

if [ -n "$ONLY" ]; then
    found=0
    for part in "${PARTS[@]}"; do
        [ "${part%%|*}" = "$ONLY" ] && found=1
    done
    [ "$found" = 1 ] || { echo "no part called '$ONLY' (see --list)" >&2; exit 2; }
fi

if [ "$MODE" = status ]; then
    recorded="$(cat "$ADAPTIVE_LOCATOR" 2>/dev/null || true)"
    if [ "$recorded" != "$REPO" ]; then
        printf '  needed   %-16s %s\n' "checkout" "the shell and session look for ${recorded:-nothing}, this checkout is $REPO"
    fi
else
    # The shell's live copy and the login session cannot see where this
    # checkout is; they read it from here.
    adaptive_record_repo
fi

pending=0
failed=0
for part in "${PARTS[@]}"; do
    IFS='|' read -r name what check command <<<"$part"
    [ -z "$ONLY" ] || [ "$ONLY" = "$name" ] || continue

    if [ "$MODE" = status ]; then
        # shellcheck disable=SC2086 # the check is a function name plus its arguments
        problem="$($check)"
        if [ -z "$problem" ]; then
            printf '  ok       %-16s %s\n' "$name" "$what"
        elif [[ "$problem" == skipped:* ]]; then
            printf '  skipped  %-16s %s\n' "$name" "${problem#skipped: }"
        else
            printf '  needed   %-16s %s\n' "$name" "$problem"
            pending=$((pending + 1))
        fi
        continue
    fi

    echo "== $name: $what"
    # shellcheck disable=SC2086
    if $command; then
        echo
    else
        echo "   $name failed (exit $?); carrying on with the rest."
        echo
        failed=$((failed + 1))
    fi
done

if [ "$MODE" = status ]; then
    session="installed"
    [ -f /usr/share/xsessions/adaptive-desktop.desktop ] || session="not installed (./install.sh --session)"
    printf '  %-8s %-16s %s\n' "$([ "$session" = installed ] && echo ok || echo needed)" "session" "Login session: $session"
    echo
    if [ "$pending" = 0 ]; then
        echo "Everything that needs no sudo is installed and current."
    else
        echo "$pending part(s) need installing or updating: ./install.sh"
    fi
    exit 0
fi

if [ "$SESSION" = 1 ] && [ -z "$ONLY" ]; then
    echo "== session: the Adaptive Desktop login session (asks for sudo)"
    "$S/install-adaptive-session.sh" || failed=$((failed + 1))
    echo
fi

if [ "$failed" != 0 ]; then
    echo "$failed part(s) failed; the rest are installed."
    exit 1
fi
echo "Installed. The shell loads its code once per login, so for the shell changes:"
echo "  $S/reload-adaptive-shell.sh --restart-shell    (X11), or log out and in"
