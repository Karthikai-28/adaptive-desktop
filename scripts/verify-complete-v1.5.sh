#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"

scripts=(
  verify-01-file-icons.sh
  verify-02-native-preview.sh
  verify-03-dock.sh
  verify-04-clock.sh
  verify-05-shell-runtime.sh
)

for script in "${scripts[@]}"; do
  echo
  echo "============================================================"
  echo "$script"
  echo "============================================================"
  "${REPO}/scripts/${script}"
done

echo
echo "============================================================"
echo "AUTOMATED VERIFICATION COMPLETE"
echo "============================================================"
echo
echo "Now perform the manual click/preview checks printed by Steps 2–4."
