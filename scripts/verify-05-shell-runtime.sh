#!/usr/bin/env bash
set -Eeuo pipefail

echo "STEP 5 — SHELL RUNTIME LOG"
echo

echo "Recent Adaptive Shell messages:"
journalctl --user -b --no-pager 2>/dev/null \
  | grep -F "[Adaptive Shell]" \
  | tail -30 \
  || true

echo
echo "Extension info:"
gnome-extensions info adaptive-shell@local | sed -n '1,40p'

echo
echo "If State is ENABLED and no JavaScript error is shown, STEP 5 passes."
