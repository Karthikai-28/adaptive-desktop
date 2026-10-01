#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
SOURCE="${REPO}/shell/adaptive-shell@local"
LIVE="${HOME}/.local/share/gnome-shell/extensions/adaptive-shell@local"

for module in "${SOURCE}/"*.js; do
  node --check "${module}"
done

test -f "${SOURCE}/metadata.json"
test -f "${SOURCE}/stylesheet.css"
test -d "${SOURCE}/assets/dock"

for icon in overview files apps workspaces search settings; do
  test -f "${SOURCE}/assets/dock/${icon}.svg"
done

if [ -d "$LIVE" ]; then
  for module in "${SOURCE}/"*.js "${SOURCE}/stylesheet.css"; do
    cmp -s "${module}" "${LIVE}/$(basename "${module}")" || {
      echo "Live extension differs from the repo ($(basename "${module}")): run scripts/sync-shell.sh"
      exit 1
    }
  done
fi

echo "Adaptive Shell source verified."
