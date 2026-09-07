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
    "adaptive-projects",
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

set_binding "adaptive-command" "Adaptive Command" "${REPO}/scripts/adaptive-command-launch.sh" "<Alt>space"
set_binding "adaptive-projects" "Adaptive Projects" "${REPO}/scripts/adaptive-projects-launch.sh" "<Alt>p"
set_binding "adaptive-window-smart" "Adaptive Smart Tile" "${REPO}/scripts/window-cli.py tile smart" "<Super><Alt>space"
set_binding "adaptive-window-left" "Adaptive Tile Left" "${REPO}/scripts/window-cli.py tile left" "<Super><Alt>Left"
set_binding "adaptive-window-right" "Adaptive Tile Right" "${REPO}/scripts/window-cli.py tile right" "<Super><Alt>Right"
set_binding "adaptive-window-center" "Adaptive Center Window" "${REPO}/scripts/window-cli.py tile center" "<Super><Alt>Down"
set_binding "adaptive-window-maximize" "Adaptive Maximize Around Dock" "${REPO}/scripts/window-cli.py tile maximize" "<Super><Alt>Up"
set_binding "adaptive-window-fullscreen" "Adaptive Toggle Fullscreen" "${REPO}/scripts/window-cli.py fullscreen" "<Super><Alt>f"
set_binding "adaptive-window-save-project" "Adaptive Save Project Window Placement" "${REPO}/scripts/window-cli.py save-project" "<Super><Alt>s"
set_binding "adaptive-window-restore-project" "Adaptive Restore Project Window Placement" "${REPO}/scripts/window-cli.py restore-project" "<Super><Alt>r"

#
# GNOME's own switch-to-workspace-left/right also list Super+Alt+Left/Right.
# Window-manager keybindings win the grab, so the Adaptive window-placement
# shortcuts silently never bind and gnome-shell logs "Failed to grab
# accelerator". Drop just those two accelerators; workspace switching keeps
# Super+Page_Up/Down and Ctrl+Alt+Left/Right.
#
release_accelerator() {
    local schema="$1"
    local key="$2"
    local unwanted="$3"

    python3 - "$schema" "$key" "$unwanted" <<'PY'
import ast
import subprocess
import sys

schema, key, unwanted = sys.argv[1], sys.argv[2], sys.argv[3]

raw = subprocess.check_output(["gsettings", "get", schema, key], text=True).strip()
if raw.startswith("@as "):
    raw = raw[4:]

try:
    values = list(ast.literal_eval(raw))
except Exception:
    sys.exit(0)

if unwanted not in values:
    sys.exit(0)

kept = [v for v in values if v != unwanted]

# Never strip a binding down to nothing; that would leave the action
# unreachable, which is worse than the conflict.
if not kept:
    print(f"  kept {unwanted} on {key}: it is the only binding left")
    sys.exit(0)

subprocess.run(["gsettings", "set", schema, key, repr(kept)], check=True)
print(f"  released {unwanted} from {key} -> {kept}")
PY
}

claim_accelerator() {
    local schema="$1"
    local key="$2"
    local wanted="$3"

    python3 - "$schema" "$key" "$wanted" <<'PY'
import ast
import subprocess
import sys

schema, key, wanted = sys.argv[1], sys.argv[2], sys.argv[3]

raw = subprocess.check_output(["gsettings", "get", schema, key], text=True).strip()
if raw.startswith("@as "):
    raw = raw[4:]

try:
    values = list(ast.literal_eval(raw))
except Exception:
    values = []

if wanted in values:
    sys.exit(0)

values.append(wanted)
subprocess.run(["gsettings", "set", schema, key, repr(values)], check=True)
print(f"  claimed {wanted} for {key} -> {values}")
PY
}

echo "Resolving accelerator conflicts:"
release_accelerator org.gnome.desktop.wm.keybindings switch-to-workspace-left '<Super><Alt>Left'
release_accelerator org.gnome.desktop.wm.keybindings switch-to-workspace-right '<Super><Alt>Right'

# Project mode moved to Alt+P so Super+P stays with Mutter's switch-monitor -
# the display projection switcher (mirror / extend / single). Earlier versions
# of this script released it, so claim it back explicitly.
claim_accelerator org.gnome.mutter.keybindings switch-monitor '<Super>p'

#
# Alt+Space opens the Command palette. GNOME's activate-window-menu holds it by
# default and has no second binding, so it is moved rather than released -
# dropping it outright would leave the window menu unreachable from the
# keyboard, which is an accessibility regression.
#
if [ "$(gsettings get org.gnome.desktop.wm.keybindings activate-window-menu)" = "['<Alt>space']" ]; then
    gsettings set org.gnome.desktop.wm.keybindings activate-window-menu "['<Alt>F3']"
    echo "  moved activate-window-menu from <Alt>space to <Alt>F3"
fi
echo

cat <<'EOF'
Installed Adaptive Desktop shortcuts:
  Alt+Space          Command palette
  Alt+P              Project mode
  Super+P            Switch display mode (mirror / extend)
  Super+Alt+Space    Smart tile active window
  Super+Alt+Left     Tile active window left
  Super+Alt+Right    Tile active window right
  Super+Alt+Down     Center active window
  Super+Alt+Up       Maximize active window around dock
  Super+Alt+F        Toggle fullscreen
  Super+Alt+S        Save active project window placement
  Super+Alt+R        Restore active project window placement
EOF
