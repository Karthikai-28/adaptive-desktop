#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
BIN="${REPO}/.local/adaptive-nautilus/bin/nautilus"
NEW_UUID="adaptive-shell-v16@local"

echo "===== GNOME ====="
gnome-shell --version

echo
echo "===== EXTENSION DIRECTORY ====="
ls -la \
  "${HOME}/.local/share/gnome-shell/extensions/${NEW_UUID}" \
  2>/dev/null || true

echo
echo "===== EXTENSION DISCOVERY ====="
gnome-extensions info "$NEW_UUID" 2>&1 || true

echo
echo "===== ENABLED EXTENSIONS SETTING ====="
gsettings get \
  org.gnome.shell \
  enabled-extensions \
  || true

echo
echo "===== USER EXTENSIONS DISABLED? ====="
gsettings get \
  org.gnome.shell \
  disable-user-extensions \
  || true

echo
echo "===== DIRECTORY HANDLER ====="
xdg-mime query default inode/directory || true

echo
echo "===== USER FILES ENTRY ====="
sed -n '1,90p' \
  "${HOME}/.local/share/applications/org.gnome.Nautilus.desktop" \
  2>/dev/null || true

echo
echo "===== RUNNING NAUTILUS EXECUTABLES ====="
for proc in /proc/[0-9]*; do
  [ -e "$proc/exe" ] || continue

  exe="$(
    readlink -f "$proc/exe" 2>/dev/null || true
  )"

  case "$exe" in
    *nautilus*)
      echo "${proc##*/} -> $exe"
      ;;
  esac
done

echo
echo "Expected:"
echo "  $BIN"

echo
echo "===== SHELL LOG ====="
journalctl --user -b --no-pager 2>/dev/null \
  | grep -E '\[Adaptive Shell( v1\.6)?\]' \
  | tail -100 \
  || true

echo
echo "===== FILE LAUNCH LOG ====="
tail -100 \
  "${HOME}/.cache/adaptive-files/launcher-v1.6.log" \
  2>/dev/null || true
