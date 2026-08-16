#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
UUID="adaptive-shell-v16@local"
SOURCE="${REPO}/shell/${UUID}/stylesheet.css"
LIVE_DIR="${HOME}/.local/share/gnome-shell/extensions/${UUID}"
LIVE="${LIVE_DIR}/stylesheet.css"

STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="${REPO}/backups/calendar-center-v1.6.2-${STAMP}"
STATE_DIR="${HOME}/.config/adaptive-desktop"
STATE_FILE="${STATE_DIR}/last-v1.6.2-calendar-backup"

step() {
  echo
  echo "============================================================"
  echo "$1"
  echo "============================================================"
}

step "STEP 0 — PREFLIGHT"

test -f "$SOURCE"

if [ ! -d "$LIVE_DIR" ]; then
  echo "Missing live v1.6 shell extension:"
  echo "  $LIVE_DIR"
  echo
  echo "Complete v1.6.1/post-login first."
  exit 2
fi

test -f "${LIVE_DIR}/extension.js"
test -f "$LIVE"

if ! gnome-extensions info "$UUID" >/dev/null 2>&1; then
  echo "GNOME Shell does not currently know $UUID."
  echo "Log out/in to Adaptive Desktop, then rerun this patch."
  exit 3
fi

echo "PASS: v1.6 shell is discoverable"

step "STEP 1 — BACKUP CURRENT CALENDAR STYLESHEET"

mkdir -p "$BACKUP" "$STATE_DIR"

cp -a "$LIVE" "${BACKUP}/stylesheet.css"

printf '%s\n' "$BACKUP" > "$STATE_FILE"

echo "Backup:"
echo "  $BACKUP"

step "STEP 2 — INSTALL ADAPTIVE CALENDAR CENTER"

cp "$SOURCE" "$LIVE"
chmod 0644 "$LIVE"

grep -q \
  'Adaptive Calendar Center v1.6.2' \
  "$LIVE"

echo "PASS: v1.6.2 calendar CSS installed"

step "STEP 3 — RELOAD EXTENSION STYLESHEET"

gnome-extensions disable "$UUID"
sleep 1
gnome-extensions enable "$UUID"
sleep 2

echo
gnome-extensions info "$UUID" \
  | sed -n '1,40p'

step "STEP 4 — COMPLETE"

echo "Open the top clock now."
echo
echo "Expected:"
echo "  - blue/cyan Today state, no Ubuntu orange"
echo "  - compact right calendar card"
echo "  - reduced empty notification dead-space"
echo "  - Adaptive notification cards"
echo "  - Adaptive Do Not Disturb control"
echo "  - Adaptive event/world-clock/weather cards"
echo
echo "Verify:"
echo "  ./scripts/verify-calendar-center-v1.6.2.sh"
