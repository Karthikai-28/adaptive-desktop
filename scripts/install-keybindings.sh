#!/usr/bin/env bash
set -Eeuo pipefail

KEY="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/adaptive-command/"
LIST="$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings)"

python3 - "$KEY" "$LIST" <<'PY' >/tmp/adaptive-keybindings.txt
import ast
import sys

key = sys.argv[1]
raw = sys.argv[2]
if raw.startswith("@as "):
    raw = raw[4:]
try:
    values = list(ast.literal_eval(raw))
except Exception:
    values = []
if key not in values:
    values.append(key)
print(repr(values))
PY

gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "$(cat /tmp/adaptive-keybindings.txt)"
gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:${KEY} name "Adaptive Command"
gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:${KEY} command "${HOME}/adaptive-desktop/scripts/adaptive-command-launch.sh"
gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:${KEY} binding "<Super>space"

echo "Installed Adaptive Command shortcut: Super+Space"
