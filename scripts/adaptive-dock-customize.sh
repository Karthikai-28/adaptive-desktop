#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${ADAPTIVE_REPO:-$HOME/adaptive-desktop}"
EXT="$REPO/shell/adaptive-shell@local/extension.js"
CSS="$REPO/shell/adaptive-shell@local/stylesheet.css"
TOKENS="$REPO/tokens/adaptive.tokens.json"
WINDOW_CLI="$REPO/scripts/window-cli.py"

fail() {
    echo "ERROR: $*" >&2
    exit 1
}

show_usage() {
    cat <<'EOF'
Usage:
  ./scripts/adaptive-dock-customize.sh [options]

Presets:
  --preset compact
  --preset balanced
  --preset large

Direct options:
  --icon-size N
  --item-width N
  --dock-height N
  --reserved-height N
  --bottom-gap N
  --radius N
  --padding-h N
  --padding-v N
  --active-scale FLOAT
  --neighbor-scale FLOAT
  --opacity FLOAT
  --duration-ms N

Examples:
  ./scripts/adaptive-dock-customize.sh --preset balanced
  ./scripts/adaptive-dock-customize.sh --icon-size 42 --dock-height 64 --reserved-height 90
  ./scripts/adaptive-dock-customize.sh --preset compact --opacity 0.14
EOF
}

[[ -f "$EXT" ]] || fail "Missing $EXT"
[[ -f "$CSS" ]] || fail "Missing $CSS"
[[ -f "$TOKENS" ]] || fail "Missing $TOKENS"
[[ -f "$WINDOW_CLI" ]] || fail "Missing $WINDOW_CLI"

preset="balanced"
icon_size=""
item_width=""
dock_height=""
reserved_height=""
bottom_gap=""
radius=""
padding_h=""
padding_v=""
active_scale=""
neighbor_scale=""
opacity=""
duration_ms=""

while (($#)); do
    case "$1" in
        --preset) preset="${2:?missing value}"; shift 2 ;;
        --icon-size) icon_size="${2:?missing value}"; shift 2 ;;
        --item-width) item_width="${2:?missing value}"; shift 2 ;;
        --dock-height) dock_height="${2:?missing value}"; shift 2 ;;
        --reserved-height) reserved_height="${2:?missing value}"; shift 2 ;;
        --bottom-gap) bottom_gap="${2:?missing value}"; shift 2 ;;
        --radius) radius="${2:?missing value}"; shift 2 ;;
        --padding-h) padding_h="${2:?missing value}"; shift 2 ;;
        --padding-v) padding_v="${2:?missing value}"; shift 2 ;;
        --active-scale) active_scale="${2:?missing value}"; shift 2 ;;
        --neighbor-scale) neighbor_scale="${2:?missing value}"; shift 2 ;;
        --opacity) opacity="${2:?missing value}"; shift 2 ;;
        --duration-ms) duration_ms="${2:?missing value}"; shift 2 ;;
        -h|--help) show_usage; exit 0 ;;
        *) fail "Unknown argument: $1" ;;
    esac
done

case "$preset" in
    compact)
        : "${icon_size:=30}"
        : "${item_width:=42}"
        : "${dock_height:=52}"
        : "${reserved_height:=72}"
        : "${bottom_gap:=8}"
        : "${radius:=16}"
        : "${padding_h:=8}"
        : "${padding_v:=3}"
        : "${active_scale:=1.12}"
        : "${neighbor_scale:=1.04}"
        : "${opacity:=0.14}"
        : "${duration_ms:=110}"
        ;;
    balanced)
        : "${icon_size:=36}"
        : "${item_width:=48}"
        : "${dock_height:=56}"
        : "${reserved_height:=80}"
        : "${bottom_gap:=10}"
        : "${radius:=18}"
        : "${padding_h:=10}"
        : "${padding_v:=5}"
        : "${active_scale:=1.18}"
        : "${neighbor_scale:=1.08}"
        : "${opacity:=0.18}"
        : "${duration_ms:=120}"
        ;;
    large)
        : "${icon_size:=42}"
        : "${item_width:=56}"
        : "${dock_height:=64}"
        : "${reserved_height:=90}"
        : "${bottom_gap:=12}"
        : "${radius:=20}"
        : "${padding_h:=12}"
        : "${padding_v:=6}"
        : "${active_scale:=1.22}"
        : "${neighbor_scale:=1.10}"
        : "${opacity:=0.22}"
        : "${duration_ms:=125}"
        ;;
    *)
        fail "Unknown preset: $preset"
        ;;
esac

python3 - "$EXT" "$CSS" "$TOKENS" "$WINDOW_CLI"     "$preset" "$icon_size" "$item_width" "$dock_height"     "$reserved_height" "$bottom_gap" "$radius" "$padding_h"     "$padding_v" "$active_scale" "$neighbor_scale" "$opacity" "$duration_ms" <<'PY'
from pathlib import Path
import json
import re
import sys

(
    ext_file,
    css_file,
    tokens_file,
    window_cli_file,
    preset,
    icon_size,
    item_width,
    dock_height,
    reserved_height,
    bottom_gap,
    radius,
    padding_h,
    padding_v,
    active_scale,
    neighbor_scale,
    opacity,
    duration_ms,
) = sys.argv[1:]

icon_size = int(icon_size)
item_width = int(item_width)
dock_height = int(dock_height)
reserved_height = int(reserved_height)
bottom_gap = int(bottom_gap)
radius = int(radius)
padding_h = int(padding_h)
padding_v = int(padding_v)
active_scale = float(active_scale)
neighbor_scale = float(neighbor_scale)
opacity = float(opacity)
duration_ms = int(duration_ms)

ext_path = Path(ext_file)
css_path = Path(css_file)
tokens_path = Path(tokens_file)
window_cli_path = Path(window_cli_file)

src = ext_path.read_text(encoding="utf-8")

def must_sub(pattern, repl, text, label):
    new_text, n = re.subn(pattern, repl, text, count=1)
    if n != 1:
        raise SystemExit(f"Failed to patch {label}")
    return new_text

src = must_sub(r'const reservedHeight = \d+;', f'const reservedHeight = {reserved_height};', src, 'reservedHeight')
src = must_sub(r'const surfaceHeight = \d+;', f'const surfaceHeight = {dock_height};', src, 'surfaceHeight')
src = must_sub(r'const bottomGap = \d+;', f'const bottomGap = {bottom_gap};', src, 'bottomGap')

src = must_sub(
    r'if \(distance === 0\) \{\n\s+scale = [0-9.]+;\n\s+lift = -\d+;\n\s+\} else if \(distance === 1\) \{',
    f'if (distance === 0) {{\n                    scale = {active_scale:.2f};\n                    lift = -5;\n                }} else if (distance === 1) {{',
    src,
    'active magnification'
)

src = must_sub(
    r'else if \(distance === 1\) \{\n\s+scale = [0-9.]+;\n\s+lift = -\d+;\n\s+\}',
    f'else if (distance === 1) {{\n                    scale = {neighbor_scale:.2f};\n                    lift = -1;\n                }}',
    src,
    'neighbor magnification'
)

ext_path.write_text(src, encoding="utf-8")

separator_height = max(24, dock_height - 26)
button_height = max(dock_height - 8, icon_size + 10)
button_width = max(item_width, icon_size + 12)
rail_spacing = max(4, round(icon_size / 8))
dot_size = 4 if icon_size <= 36 else 5
rail_border_alpha = min(opacity + 0.06, 0.32)
rail_inner_alpha = min(opacity + 0.03, 0.28)

css_block = f"""/* Adaptive dock visual customization v2.3 START */
.adaptive-dock-reservation {{
    margin: 0;
    padding: 0;
    background-color: transparent;
    border: 0;
    box-shadow: none;
}}

.adaptive-rail {{
    margin: 0;
    padding: {padding_v}px {padding_h}px {max(2, padding_v - 1)}px {padding_h}px;
    spacing: {rail_spacing}px;
    border-radius: {radius}px;
    background-color: rgba(112, 180, 255, {opacity:.2f});
    border: 1px solid rgba(255, 255, 255, {rail_border_alpha:.2f});
    box-shadow:
        0 8px 24px rgba(0, 0, 0, 0.28),
        inset 0 1px 0 rgba(255, 255, 255, {rail_inner_alpha:.2f});
}}

.adaptive-window-list {{
    spacing: {max(2, rail_spacing - 1)}px;
}}

.adaptive-dock-button {{
    width: {button_width}px;
    height: {button_height}px;
    padding: 1px 2px;
    border-radius: {max(12, radius - 6)}px;
    background-color: transparent;
    border: 1px solid transparent;
}}

.adaptive-dock-button:hover {{
    background-color: rgba(255, 255, 255, 0.07);
    border: 1px solid rgba(255, 255, 255, 0.10);
}}

.adaptive-app-icon,
.adaptive-dock-icon {{
    icon-size: {icon_size}px;
}}

.adaptive-app-dock-content {{
    spacing: 1px;
}}

.adaptive-running-indicators {{
    height: {dot_size + 1}px;
    spacing: 3px;
}}

.adaptive-running-dot {{
    width: {dot_size}px;
    height: {dot_size}px;
    border-radius: {dot_size // 2}px;
}}

.adaptive-rail-rule {{
    width: 1px;
    height: {separator_height}px;
    margin: 7px 3px 4px 3px;
    background-color: rgba(255, 255, 255, 0.14);
}}
/* Adaptive dock visual customization v2.3 END */
""" + "\n"

css = css_path.read_text(encoding="utf-8")
start = '/* Adaptive dock visual customization v2.3 START */'
end = '/* Adaptive dock visual customization v2.3 END */'
if start in css and end in css:
    a = css.find(start)
    b = css.find(end, a)
    b = css.find('\n', b)
    if b == -1:
        b = len(css)
    else:
        b += 1
    css = css[:a] + css_block + css[b:]
else:
    css += "\n\n" + css_block
css_path.write_text(css, encoding="utf-8")

window_cli = window_cli_path.read_text(encoding="utf-8")
window_cli = must_sub(r'DOCK_RESERVED_HEIGHT = \d+', f'DOCK_RESERVED_HEIGHT = {reserved_height}', window_cli, 'DOCK_RESERVED_HEIGHT')
window_cli_path.write_text(window_cli, encoding="utf-8")

tokens = json.loads(tokens_path.read_text(encoding="utf-8"))
shell = tokens.setdefault("shell", {})
shell.update({
    "dock.position": "bottom-center",
    "dock.style": "glass",
    "dock.preset": preset,
    "dock.icon": icon_size,
    "dock.item.width": item_width,
    "dock.height": dock_height,
    "dock.reserved_height": reserved_height,
    "dock.bottom_margin": bottom_gap,
    "dock.radius": radius,
    "dock.padding_h": padding_h,
    "dock.padding_v": padding_v,
    "dock.hover.scale": active_scale,
    "dock.neighbor.scale": neighbor_scale,
    "dock.hover.duration_ms": duration_ms,
    "dock.opacity": opacity,
    "dock.separator.height": separator_height,
})
tokens_path.write_text(json.dumps(tokens, indent=2) + "\n", encoding="utf-8")

print("Dock customization applied:")
print({
    "preset": preset,
    "icon_size": icon_size,
    "item_width": item_width,
    "dock_height": dock_height,
    "reserved_height": reserved_height,
    "bottom_gap": bottom_gap,
    "radius": radius,
    "padding_h": padding_h,
    "padding_v": padding_v,
    "active_scale": active_scale,
    "neighbor_scale": neighbor_scale,
    "opacity": opacity,
    "duration_ms": duration_ms,
})
PY

"$REPO/scripts/sync-shell.sh"

echo
echo "Dock customization synced."
echo "Restart GNOME Shell to apply JS changes:"
echo "  $REPO/scripts/reload-adaptive-shell.sh --restart-shell"
