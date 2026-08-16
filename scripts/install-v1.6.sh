#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
PREFIX="${REPO}/.local/adaptive-nautilus"

OLD_UUID="adaptive-shell@local"
NEW_UUID="adaptive-shell-v16@local"

OLD_LIVE="${HOME}/.local/share/gnome-shell/extensions/${OLD_UUID}"
NEW_LIVE="${HOME}/.local/share/gnome-shell/extensions/${NEW_UUID}"
NEW_SOURCE="${REPO}/shell/${NEW_UUID}"

STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="${REPO}/backups/routing-fix-v1.6-${STAMP}"
STATE_DIR="${HOME}/.config/adaptive-desktop"
STATE_FILE="${STATE_DIR}/last-v1.6-backup"

trap 'echo; echo "v1.6 INSTALL FAILED at line $LINENO"' ERR

step() {
  echo
  echo "================================================================"
  echo "$1"
  echo "================================================================"
}

step "STEP 0 — PREFLIGHT"

test -x "${PREFIX}/bin/nautilus"
echo "PASS: local Nautilus exists"

GNOME_VERSION="$(gnome-shell --version 2>/dev/null || true)"
echo "Detected: $GNOME_VERSION"

case "$GNOME_VERSION" in
  *" 42."*)
    echo "PASS: GNOME Shell 42"
    ;;
  *)
    echo "This package is intentionally limited to GNOME Shell 42."
    exit 4
    ;;
esac

command -v gnome-extensions >/dev/null
command -v gnome-control-center >/dev/null
command -v xdg-mime >/dev/null

step "STEP 1 — BACKUP"

mkdir -p "$BACKUP" "$STATE_DIR"

for path in \
  "$OLD_LIVE" \
  "$NEW_LIVE" \
  "${HOME}/.local/share/applications/org.gnome.Nautilus.desktop" \
  "${HOME}/.local/share/applications/com.karthi.AdaptiveFiles.desktop"
do
  if [ -e "$path" ]; then
    rel="${path#${HOME}/}"
    dst="${BACKUP}/${rel}"
    mkdir -p "$(dirname "$dst")"
    cp -a "$path" "$dst"
  fi
done

printf '%s\n' "$BACKUP" > "$STATE_FILE"

echo "Backup:"
echo "  $BACKUP"

step "STEP 2 — UPDATE FILE PREVIEW / ICON LAYER"

"${REPO}/scripts/phase2.5-install-native-preview.sh"

step "STEP 3 — MAKE ADAPTIVE FILES THE USER-LEVEL FILES ROUTE"

"${REPO}/scripts/install-file-routing-v1.6.sh"

step "STEP 4 — DISABLE THE STALE SHELL EXTENSION"

gnome-extensions disable "$OLD_UUID" >/dev/null 2>&1 || true
gnome-extensions disable "$NEW_UUID" >/dev/null 2>&1 || true
sleep 1

step "STEP 5 — INSTALL A FRESH SHELL MODULE UNDER A NEW UUID"

rm -rf "$NEW_LIVE"
mkdir -p "$(dirname "$NEW_LIVE")"
cp -a "$NEW_SOURCE" "$NEW_LIVE"

find "$NEW_LIVE" -type d -exec chmod 0755 {} +
find "$NEW_LIVE" -type f -exec chmod 0644 {} +

if command -v node >/dev/null 2>&1; then
  node --check "${NEW_LIVE}/extension.js"
  echo "PASS: extension JavaScript syntax"
fi

# New UUID is deliberate: GNOME Shell cannot reuse the old adaptive-shell
# JavaScript module from memory.
gnome-extensions enable "$NEW_UUID"

sleep 3

echo
echo "New extension:"
gnome-extensions info "$NEW_UUID" | sed -n '1,40p'

step "STEP 6 — FILE LAUNCHER SELF-TEST"

"${REPO}/scripts/adaptive-files-launch-v1.6.sh" --self-test

step "STEP 7 — ROUTING CHECK"

DEFAULT_HANDLER="$(
  xdg-mime query default inode/directory || true
)"

echo "inode/directory -> ${DEFAULT_HANDLER}"

if [ "$DEFAULT_HANDLER" != "org.gnome.Nautilus.desktop" ]; then
  echo "ERROR: directory default did not become org.gnome.Nautilus.desktop"
  exit 8
fi

grep -q "adaptive-files-launch-v1.6.sh" \
  "${HOME}/.local/share/applications/org.gnome.Nautilus.desktop"

echo "PASS: standard Files desktop ID routes to Adaptive Files"

step "STEP 8 — COMPLETE"

echo "v1.6 is installed."
echo
echo "Verify:"
echo "  cd ~/adaptive-desktop"
echo "  ./scripts/verify-v1.6.sh"
echo
echo "Expected immediately:"
echo "  - no stock bottom dash in Overview"
echo "  - functional left rail"
echo "  - top GNOME time visible"
echo "  - normal Files icon routes to Adaptive Files"
