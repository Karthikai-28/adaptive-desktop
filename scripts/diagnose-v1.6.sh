#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
BIN="${REPO}/.local/adaptive-nautilus/bin/nautilus"

echo "===== EXTENSIONS ====="
gnome-extensions info adaptive-shell@local 2>/dev/null | sed -n '1,30p' || true
echo
gnome-extensions info adaptive-shell-v16@local 2>/dev/null | sed -n '1,40p' || true

echo
echo "===== DIRECTORY HANDLER ====="
xdg-mime query default inode/directory || true

echo
echo "===== USER FILES DESKTOP ENTRY ====="
sed -n '1,80p' "${HOME}/.local/share/applications/org.gnome.Nautilus.desktop" 2>/dev/null || true

echo
echo "===== RUNNING NAUTILUS EXECUTABLES ====="
for proc in /proc/[0-9]*; do
  [ -e "$proc/exe" ] || continue
  exe="$(readlink -f "$proc/exe" 2>/dev/null || true)"

  case "$exe" in
    *nautilus*)
      echo "${proc##*/} -> $exe"
      ;;
  esac
done

echo
echo "Expected local binary:"
echo "  $BIN"

echo
echo "===== ADAPTIVE SHELL LOG ====="
journalctl --user -b --no-pager 2>/dev/null \
  | grep -F "[Adaptive Shell v1.6]" \
  | tail -80 \
  || true

echo
echo "===== ADAPTIVE FILES LAUNCH LOG ====="
tail -80 "${HOME}/.cache/adaptive-files/launcher-v1.6.log" 2>/dev/null || true
