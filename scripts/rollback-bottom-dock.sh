#!/usr/bin/env bash
set -Eeuo pipefail
REPO="${ADAPTIVE_REPO:-$HOME/adaptive-desktop}"
STATE_FILE="$HOME/.config/adaptive-desktop/last-bottom-dock-backup"
[[ -f "$STATE_FILE" ]] || { echo "No bottom-dock backup pointer." >&2; exit 2; }
BACKUP="$(cat "$STATE_FILE")"
[[ -d "$BACKUP" ]] || { echo "Backup missing: $BACKUP" >&2; exit 3; }

cp -a "$BACKUP/shell/extension.js" "$REPO/shell/adaptive-shell@local/extension.js"
cp -a "$BACKUP/shell/stylesheet.css" "$REPO/shell/adaptive-shell@local/stylesheet.css"
cp -a "$BACKUP/scripts/window-cli.py" "$REPO/scripts/window-cli.py"
cp -a "$BACKUP/scripts/record-live-verification.py" "$REPO/scripts/record-live-verification.py"
cp -a "$BACKUP/tokens/adaptive.tokens.json" "$REPO/tokens/adaptive.tokens.json"
if [[ -f "$BACKUP/docs/BACKLOG.md" ]]; then
    cp -a "$BACKUP/docs/BACKLOG.md" "$REPO/docs/BACKLOG.md"
fi

"$REPO/scripts/sync-shell.sh"
echo "Rollback files restored and synced."
echo "Apply with: $REPO/scripts/reload-adaptive-shell.sh --restart-shell"
