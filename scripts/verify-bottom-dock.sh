#!/usr/bin/env bash
set -Eeuo pipefail
REPO="${ADAPTIVE_REPO:-$HOME/adaptive-desktop}"
# The shell's one class lives in extension.js and the shell*.js files beside it.
EXT=("$REPO/shell/adaptive-shell@local/extension.js" "$REPO/shell/adaptive-shell@local/"shell[A-Z]*.js)
CSS="$REPO/shell/adaptive-shell@local/stylesheet.css"

for module in "${EXT[@]}"; do
    node --check "$module"
done
python3 -m py_compile "$REPO/scripts/window-cli.py"
python3 -m json.tool "$REPO/tokens/adaptive.tokens.json" >/dev/null

grep -q 'const AppFavorites = imports.ui.appFavorites' "${EXT[@]}"
grep -q 'Keep in Dock' "${EXT[@]}"
grep -q 'Remove from Dock' "${EXT[@]}"
grep -q '_magnifyDock' "${EXT[@]}"
grep -q 'adaptive-running-dot' "$CSS"
grep -q 'monitor.y + monitor.height - height - 12' "${EXT[@]}"

if grep -q "'Command'.*=> this._openCommand" "${EXT[@]}"; then
    echo "FAIL: permanent Command dock button still found" >&2
    exit 1
fi

if grep -q "DOCK_WIDTH =" "$REPO/scripts/window-cli.py"; then
    echo "FAIL: window-cli still reserves a left dock width" >&2
    exit 1
fi

echo "PASS: bottom dock source checks"
echo "favorite-apps:"
gsettings get org.gnome.shell favorite-apps || true

echo "Nautilus click policy:"
gsettings get org.gnome.nautilus.preferences click-policy || true

echo "Nautilus tab position:"
gsettings get org.gnome.nautilus.preferences tabs-open-position || true
