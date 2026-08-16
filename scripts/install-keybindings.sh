#!/usr/bin/env bash
set -Eeuo pipefail

BASE="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"
REPO="${HOME}/adaptive-desktop"

python3 - "$BASE" <<'PY' >/tmp/adaptive-keybindings.txt
import ast
import sys

base = sys.argv[1].rstrip("/")
raw = __import__("subprocess").check_output(
    ["gsettings", "get", "org.gnome.settings-daemon.plugins.media-keys", "custom-keybindings"],
    text=True,
).strip()
if raw.startswith("@as "):
    raw = raw[4:]
try:
    values = list(ast.literal_eval(raw))
except Exception:
    values = []

for name in [
    "adaptive-command",
    "adaptive-window-smart",
    "adaptive-window-left",
    "adaptive-window-right",
    "adaptive-window-center",
    "adaptive-window-maximize",
    "adaptive-window-fullscreen",
    "adaptive-window-save-project",
    "adaptive-window-restore-project",
]:
    key = f"{base}/{name}/"
    if key not in values:
        values.append(key)

print(repr(values))
PY

gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "$(cat /tmp/adaptive-keybindings.txt)"

set_binding() {
    local name="$1"
    local title="$2"
    local command="$3"
    local binding="$4"
    local key="${BASE}/${name}/"

    gsettings set "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:${key}" name "${title}"
    gsettings set "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:${key}" command "${command}"
    gsettings set "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:${key}" binding "${binding}"
}

set_binding "adaptive-command" "Adaptive Command" "${REPO}/scripts/adaptive-command-launch.sh" "<Super>space"
set_binding "adaptive-window-smart" "Adaptive Smart Tile" "${REPO}/scripts/window-cli.py tile smart" "<Super><Alt>space"
set_binding "adaptive-window-left" "Adaptive Tile Left" "${REPO}/scripts/window-cli.py tile left" "<Super><Alt>Left"
set_binding "adaptive-window-right" "Adaptive Tile Right" "${REPO}/scripts/window-cli.py tile right" "<Super><Alt>Right"
set_binding "adaptive-window-center" "Adaptive Center Window" "${REPO}/scripts/window-cli.py tile center" "<Super><Alt>Down"
set_binding "adaptive-window-maximize" "Adaptive Maximize Around Dock" "${REPO}/scripts/window-cli.py tile maximize" "<Super><Alt>Up"
set_binding "adaptive-window-fullscreen" "Adaptive Toggle Fullscreen" "${REPO}/scripts/window-cli.py fullscreen" "<Super><Alt>f"
set_binding "adaptive-window-save-project" "Adaptive Save Project Window Placement" "${REPO}/scripts/window-cli.py save-project" "<Super><Alt>s"
set_binding "adaptive-window-restore-project" "Adaptive Restore Project Window Placement" "${REPO}/scripts/window-cli.py restore-project" "<Super><Alt>r"

cat <<'EOF'
Installed Adaptive Desktop shortcuts:
  Super+Space        Command palette
  Super+Alt+Space    Smart tile active window
  Super+Alt+Left     Tile active window left
  Super+Alt+Right    Tile active window right
  Super+Alt+Down     Center active window
  Super+Alt+Up       Maximize active window around dock
  Super+Alt+F        Toggle fullscreen
  Super+Alt+S        Save active project window placement
  Super+Alt+R        Restore active project window placement
EOF
