#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
BIN="${REPO}/.local/adaptive-nautilus/bin/nautilus"

echo "Launching standard desktop ID:"
echo "  org.gnome.Nautilus.desktop"

gtk-launch org.gnome.Nautilus >/dev/null 2>&1 &

for _ in $(seq 1 20); do
  sleep 0.25

  for proc in /proc/[0-9]*; do
    [ -e "$proc/exe" ] || continue

    exe="$(
      readlink -f "$proc/exe" 2>/dev/null || true
    )"

    if [ "$exe" = "$BIN" ]; then
      echo "PASS:"
      echo "  ${proc##*/} -> $exe"
      exit 0
    fi
  done
done

echo "FAIL: local Adaptive Files process was not detected."
echo
echo "Run:"
echo "  ./scripts/diagnose-v1.6.1.sh"
exit 20
