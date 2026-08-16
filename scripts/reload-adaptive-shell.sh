#!/usr/bin/env bash
set -Eeuo pipefail

UUID="adaptive-shell@local"

echo "Reloading $UUID ..."

gnome-extensions disable "$UUID" >/dev/null 2>&1 || true
sleep 1
gnome-extensions enable "$UUID"
sleep 2

gnome-extensions info "$UUID" | sed -n '1,30p'
