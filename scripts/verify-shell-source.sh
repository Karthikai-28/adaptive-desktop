#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
SOURCE="${REPO}/shell/adaptive-shell@local"
LIVE="${HOME}/.local/share/gnome-shell/extensions/adaptive-shell@local"

node --check "${SOURCE}/extension.js"

test -f "${SOURCE}/metadata.json"
test -f "${SOURCE}/stylesheet.css"
test -d "${SOURCE}/assets/dock"

for icon in overview files apps workspaces search settings; do
  test -f "${SOURCE}/assets/dock/${icon}.svg"
done

if [ -d "$LIVE" ]; then
  cmp -s "${SOURCE}/extension.js" "${LIVE}/extension.js"
  cmp -s "${SOURCE}/stylesheet.css" "${LIVE}/stylesheet.css"
fi

echo "Adaptive Shell source verified."
