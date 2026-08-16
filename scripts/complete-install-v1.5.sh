#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
PREFIX="${REPO}/.local/adaptive-nautilus"
UUID="adaptive-shell@local"
LIVE_EXT="${HOME}/.local/share/gnome-shell/extensions/${UUID}"
SOURCE_EXT="${REPO}/shell/${UUID}"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="${REPO}/backups/complete-v1.5-${STAMP}"
STATE_DIR="${HOME}/.config/adaptive-desktop"
STATE_FILE="${STATE_DIR}/last-complete-patch-backup"

trap 'echo; echo "INSTALL FAILED at line $LINENO"; echo "Nothing after this step was assumed successful."' ERR

step() {
  echo
  echo "================================================================"
  echo "$1"
  echo "================================================================"
}

step "STEP 0 — PREFLIGHT"

if [ ! -d "$REPO" ]; then
  echo "Missing repository: $REPO"
  exit 2
fi

if [ ! -x "${PREFIX}/bin/nautilus" ]; then
  echo "Missing locally built Nautilus 42.6:"
  echo "  ${PREFIX}/bin/nautilus"
  echo
  echo "Do not continue until the Nautilus baseline is restored."
  exit 3
fi

GNOME_VERSION="$(gnome-shell --version 2>/dev/null || true)"
echo "GNOME: $GNOME_VERSION"

case "$GNOME_VERSION" in
  *" 42."*)
    echo "PASS: GNOME Shell 42 target"
    ;;
  *)
    echo "This patch is intentionally limited to GNOME Shell 42."
    echo "Detected: $GNOME_VERSION"
    exit 4
    ;;
esac

command -v gnome-extensions >/dev/null
command -v gnome-control-center >/dev/null

echo "PASS: preflight"

step "STEP 1 — BACKUP CURRENT WORKING STATE"

mkdir -p "$BACKUP" "$STATE_DIR"

if [ -d "$LIVE_EXT" ]; then
  mkdir -p "${BACKUP}/gnome-shell"
  cp -a "$LIVE_EXT" "${BACKUP}/gnome-shell/"
fi

for path in \
  "${PREFIX}/share/themes/AdaptiveFiles" \
  "${PREFIX}/share/icons/AdaptiveFilesIcons" \
  "${PREFIX}/share/nautilus-python/extensions/adaptive_preview.py" \
  "${PREFIX}/share/adaptive-files/preview.css"
do
  if [ -e "$path" ]; then
    rel="${path#${PREFIX}/}"
    dst="${BACKUP}/adaptive-nautilus/${rel}"
    mkdir -p "$(dirname "$dst")"
    cp -a "$path" "$dst"
  fi
done

if [ -f "${HOME}/.local/share/applications/com.karthi.AdaptiveFiles.desktop" ]; then
  mkdir -p "${BACKUP}/desktop"
  cp -a \
    "${HOME}/.local/share/applications/com.karthi.AdaptiveFiles.desktop" \
    "${BACKUP}/desktop/"
fi

printf '%s\n' "$BACKUP" > "$STATE_FILE"

echo "Backup:"
echo "  $BACKUP"

step "STEP 2 — INSTALL NATIVE PREVIEW + LANGUAGE ICONS"

"${REPO}/scripts/phase2.5-install-native-preview.sh"

step "STEP 3 — INSTALL ADAPTIVE FILES DESKTOP ENTRY"

"${REPO}/scripts/install-adaptive-files-desktop-entry.sh"

step "STEP 4 — INSTALL WORKING ADAPTIVE SHELL / DOCK"

gnome-extensions disable "$UUID" >/dev/null 2>&1 || true
sleep 1

rm -rf "$LIVE_EXT"
mkdir -p "$(dirname "$LIVE_EXT")"
cp -a "$SOURCE_EXT" "$LIVE_EXT"

# Ensure GNOME Shell can read the extension files.
find "$LIVE_EXT" -type d -exec chmod 0755 {} +
find "$LIVE_EXT" -type f -exec chmod 0644 {} +

if command -v node >/dev/null 2>&1; then
  node --check "${LIVE_EXT}/extension.js"
  echo "PASS: extension.js syntax"
fi

gnome-extensions enable "$UUID"
sleep 3

echo "Adaptive Shell state:"
gnome-extensions info "$UUID" | sed -n '1,35p'

step "STEP 5 — SELF-TEST FILE EXPLORER LAUNCHER"

"${REPO}/scripts/adaptive-files-launch.sh" --self-test

step "STEP 6 — VERIFY INSTALLED ICON SET"

"${REPO}/scripts/verify-01-file-icons.sh"

step "STEP 7 — FINAL INSTALL SUMMARY"

echo "Installed:"
echo "  - language-specific file icons"
echo "  - Ubuntu/GNOME native PDF/image thumbnail integration"
echo "  - GtkSourceView source-code preview"
echo "  - working Adaptive Files dock button"
echo "  - working Apps / Workspaces / Search buttons"
echo "  - working Settings button"
echo "  - restored stock GNOME clock/calendar with Adaptive styling"
echo
echo "Run full verification:"
echo "  cd ~/adaptive-desktop"
echo "  ./scripts/verify-complete-v1.5.sh"
echo
echo "Rollback if necessary:"
echo "  ./scripts/rollback-complete-v1.5.sh"
