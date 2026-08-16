#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="$HOME/.local/lib/adaptive-files"
BIN="$HOME/.local/bin"
APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor/scalable/apps"

mkdir -p "$LIB/assets" "$BIN" "$APPS" "$ICONS"

install -m 0755 "$ROOT/main.py" "$LIB/main.py"
install -m 0644 "$ROOT/style.css" "$LIB/style.css"
cp -f "$ROOT"/assets/*.svg "$LIB/assets/"
install -m 0644 "$ROOT/assets/app-logo.svg" "$ICONS/adaptive-files.svg"
install -m 0644 "$ROOT/com.karthi.AdaptiveFiles.desktop" "$APPS/com.karthi.AdaptiveFiles.desktop"

cat > "$BIN/adaptive-files" <<'EOF'
#!/usr/bin/env bash
exec /usr/bin/python3 "$HOME/.local/lib/adaptive-files/main.py" "$@"
EOF
chmod 0755 "$BIN/adaptive-files"

update-desktop-database "$APPS" 2>/dev/null || true
gtk-update-icon-cache -q "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

echo "Installed Adaptive Files."
echo "Launcher: $BIN/adaptive-files"
echo "Desktop entry: $APPS/com.karthi.AdaptiveFiles.desktop"
