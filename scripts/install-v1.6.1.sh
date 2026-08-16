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
BACKUP="${REPO}/backups/routing-fix-v1.6.1-${STAMP}"
STATE_DIR="${HOME}/.config/adaptive-desktop"
STATE_FILE="${STATE_DIR}/last-v1.6.1-backup"
MARKER="${STATE_DIR}/v1.6.1-relogin-required"

trap 'echo; echo "v1.6.1 INSTALL FAILED at line $LINENO"' ERR

step() {
  echo
  echo "================================================================"
  echo "$1"
  echo "================================================================"
}

step "STEP 0 — PREFLIGHT"

test -x "${PREFIX}/bin/nautilus"
echo "PASS: local Nautilus exists"

GNOME_VERSION="$(
  gnome-shell --version 2>/dev/null || true
)"

echo "Detected: $GNOME_VERSION"

case "$GNOME_VERSION" in
  *" 42."*)
    echo "PASS: GNOME Shell 42"
    ;;
  *)
    echo "This patch is intentionally limited to GNOME Shell 42."
    exit 4
    ;;
esac

command -v gnome-extensions >/dev/null
command -v gnome-control-center >/dev/null
command -v gsettings >/dev/null
command -v xdg-mime >/dev/null

test -d "$NEW_SOURCE"
echo "PASS: v1.6 shell source exists"

step "STEP 1 — BACKUP CURRENT STATE"

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

gsettings get \
  org.gnome.shell \
  enabled-extensions \
  > "${BACKUP}/enabled-extensions.txt" \
  || true

printf '%s\n' "$BACKUP" > "$STATE_FILE"

echo "Backup:"
echo "  $BACKUP"

step "STEP 2 — ENSURE FILE PREVIEW / ICON LAYER"

"${REPO}/scripts/phase2.5-install-native-preview.sh"

step "STEP 3 — ENSURE ALL FILES ROUTE TO ADAPTIVE FILES"

"${REPO}/scripts/install-file-routing-v1.6.sh"

grep -q \
  "adaptive-files-launch-v1.6.sh" \
  "${HOME}/.local/share/applications/org.gnome.Nautilus.desktop"

echo "PASS: standard Files desktop ID routes to Adaptive Files"

step "STEP 4 — DISABLE OLD LIVE EXTENSION"

gnome-extensions disable \
  "$OLD_UUID" \
  >/dev/null 2>&1 \
  || true

# The current shell knows OLD_UUID, so disabling it is safe immediately.
echo "Old extension disabled in current Shell."

step "STEP 5 — INSTALL NEW EXTENSION FILES"

rm -rf "$NEW_LIVE"
mkdir -p "$(dirname "$NEW_LIVE")"
cp -a "$NEW_SOURCE" "$NEW_LIVE"

find "$NEW_LIVE" \
  -type d \
  -exec chmod 0755 {} +

find "$NEW_LIVE" \
  -type f \
  -exec chmod 0644 {} +

test -f "${NEW_LIVE}/metadata.json"
test -f "${NEW_LIVE}/extension.js"
test -f "${NEW_LIVE}/stylesheet.css"

if command -v node >/dev/null 2>&1; then
  node --check "${NEW_LIVE}/extension.js"
  echo "PASS: extension.js syntax"
fi

echo "PASS: new extension files staged:"
echo "  $NEW_LIVE"

step "STEP 6 — STAGE NEW UUID IN GNOME SETTINGS"

"${REPO}/scripts/stage-shell-v1.6.1.sh"

step "STEP 7 — CHECK WHETHER CURRENT SHELL HAS ALREADY DISCOVERED IT"

if gnome-extensions info \
  "$NEW_UUID" \
  >/dev/null 2>&1
then
  echo "Current Shell already sees the new UUID."

  gnome-extensions enable "$NEW_UUID"
  sleep 2

  gnome-extensions info "$NEW_UUID" \
    | sed -n '1,40p'

  rm -f "$MARKER"

  echo
  echo "No logout is required on this run."
else
  echo "Current GNOME Shell has NOT rescanned the new UUID."
  echo "This is the state that caused v1.6 to abort."
  echo
  echo "The extension files and enabled-extension setting are now staged"
  echo "correctly for the NEXT GNOME Shell startup."

  printf '%s\n' \
    "Log out and back into Adaptive Desktop once." \
    > "$MARKER"
fi

step "STEP 8 — FILE ROUTING SELF-TEST"

"${REPO}/scripts/adaptive-files-launch-v1.6.sh" \
  --self-test

echo
echo "User Files desktop entry:"
grep -E \
  '^(Name|Exec|Icon|DBusActivatable)=' \
  "${HOME}/.local/share/applications/org.gnome.Nautilus.desktop"

step "STEP 9 — INSTALL STAGED SUCCESSFULLY"

if [ -f "$MARKER" ]; then
  echo "ONE LOGOUT / LOGIN IS REQUIRED."
  echo
  echo "1. Save your work."
  echo "2. Log out normally."
  echo "3. At the login screen select 'Adaptive Desktop'."
  echo "4. Log in."
  echo "5. Open Terminal and run:"
  echo
  echo "   cd ~/adaptive-desktop"
  echo "   ./scripts/post-login-v1.6.1.sh"
  echo
  echo "Do not run the old v1.6 installer again."
else
  echo "The fresh Shell module is already active."
  echo
  echo "Run:"
  echo "  ./scripts/verify-v1.6.1.sh"
fi
