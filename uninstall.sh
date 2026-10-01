#!/usr/bin/env bash
#
# Take Adaptive Desktop's user-level parts off this account.
#
#   ./uninstall.sh --dry-run   say what would be removed; change nothing
#   ./uninstall.sh             remove them
#   ./uninstall.sh --session   also remove the login session (asks for sudo)
#
# What goes: the timers and services, the autostart entries, the app-grid
# entries, the Adaptive keyboard shortcuts, and the shell extension is turned
# off. What stays: your data - the project registry, notes, snippets and
# settings in ~/.config/adaptive-desktop and ~/.local/share/adaptive-desktop -
# and the extension's files, so ./install.sh brings everything back.
#
# Ubuntu's own session is never touched. See docs/UNINSTALL_AND_RECOVERY.md.
set -Euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNITS="$HOME/.config/systemd/user"
APPS="$HOME/.local/share/applications"
AUTOSTART="$HOME/.config/autostart"
MEDIA_KEYS="org.gnome.settings-daemon.plugins.media-keys"

DRY=0
SESSION=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY=1 ;;
        --session) SESSION=1 ;;
        -h|--help) sed -n '3,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
    esac
done

say() { echo "  $([ "$DRY" = 1 ] && echo 'would' || echo 'did') $*"; }
run() { [ "$DRY" = 1 ] || "$@"; }

echo "Timers and services"
for unit in adaptive-wallpaper.timer adaptive-index.timer adaptive-power-auto.service; do
    if [ -f "$UNITS/$unit" ]; then
        run systemctl --user disable --now "$unit" 2>/dev/null || true
        say "disable $unit"
    fi
done
for file in adaptive-wallpaper.service adaptive-wallpaper.timer adaptive-index.service \
    adaptive-index.timer adaptive-power-auto.service; do
    if [ -f "$UNITS/$file" ]; then
        run rm -f "$UNITS/$file"
        say "remove $UNITS/$file"
    fi
done
run systemctl --user daemon-reload 2>/dev/null || true

echo "Autostart and app-grid entries"
# The lid watcher is not in this list: while the Adaptive session can still be
# logged into, it is what puts the laptop to sleep when the lid closes
# (docs/POWER_POLICY.md). It goes with the session, below.
for file in "$AUTOSTART/adaptive-project-context.desktop" "$AUTOSTART/adaptive-gestures.desktop" \
    "$APPS/adaptive-project-context.desktop" "$APPS/com.karthi.AdaptiveSettings.desktop" \
    "$APPS/com.karthi.AdaptiveGestures.desktop" \
    "$HOME/.local/share/gnome-shell/search-providers/org.adaptive.ProjectContext.search-provider.ini"; do
    if [ -f "$file" ]; then
        run rm -f "$file"
        say "remove $file"
    fi
done

echo "Keyboard shortcuts"
# Only the adaptive-* slots: custom shortcuts you made yourself are kept.
kept="$(python3 - <<'PY'
import ast, subprocess
raw = subprocess.run(["gsettings", "get", "org.gnome.settings-daemon.plugins.media-keys",
                      "custom-keybindings"], capture_output=True, text=True).stdout.strip()
raw = raw[4:] if raw.startswith("@as ") else raw
try:
    values = list(ast.literal_eval(raw))
except Exception:
    values = []
ours = [v for v in values if v.rstrip("/").rsplit("/", 1)[-1].startswith("adaptive-")]
print(len(ours))
print(repr([v for v in values if v not in ours]))
print("\n".join(ours))
PY
)"
count="$(sed -n 1p <<<"$kept")"
if [ "${count:-0}" != 0 ]; then
    while read -r path; do
        [ -n "$path" ] || continue
        for key in name command binding; do
            run gsettings reset "$MEDIA_KEYS.custom-keybinding:$path" "$key"
        done
    done <<<"$(sed -n '3,$p' <<<"$kept")"
    run gsettings set "$MEDIA_KEYS" custom-keybindings "$(sed -n 2p <<<"$kept")"
    say "remove $count Adaptive shortcut(s)"
fi

echo "Shell extension"
if gnome-extensions list --enabled 2>/dev/null | grep -qx 'adaptive-shell@local'; then
    run gnome-extensions disable adaptive-shell@local
    say "turn off adaptive-shell@local (its files stay)"
fi

echo "Background processes"
for pid in $(pgrep -x python3 || true); do
    if tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null |
        grep -qE "adaptive-gestures\.py|project-context/main\.py|adaptive-power-auto\.py"; then
        run kill "$pid" 2>/dev/null || true
        say "stop process $pid"
    fi
done

if [ "$SESSION" = 1 ]; then
    echo "Login session"
    if [ "$DRY" = 1 ]; then
        say "run scripts/remove-adaptive-session.sh (sudo)"
    else
        "$REPO/scripts/remove-adaptive-session.sh"
    fi
    if [ -f "$AUTOSTART/adaptive-lid-watch.desktop" ]; then
        run rm -f "$AUTOSTART/adaptive-lid-watch.desktop"
        say "remove $AUTOSTART/adaptive-lid-watch.desktop"
    fi
fi

echo
echo "Your data was left alone:"
echo "  ~/.config/adaptive-desktop   ~/.local/share/adaptive-desktop"
[ "$DRY" = 1 ] && echo "Nothing was changed (dry run)."
exit 0
