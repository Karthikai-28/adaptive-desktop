#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
CLI="${REPO}/scripts/project-cli.py"
AUTOSTART_SCRIPT="${REPO}/scripts/project-context-autostart.sh"
AUTOSTART="${HOME}/.config/autostart/adaptive-project-context.desktop"
SEARCH_PROVIDER="${HOME}/.local/share/gnome-shell/search-providers/org.adaptive.ProjectContext.search-provider.ini"

test -x "${REPO}/services/project-context/main.py"
test -x "$AUTOSTART_SCRIPT"
test -f "$AUTOSTART"
test -f "$SEARCH_PROVIDER"
grep -q "Exec=${AUTOSTART_SCRIPT}" "$AUTOSTART"
bash -n "$AUTOSTART_SCRIPT"
desktop-file-validate "$AUTOSTART"

python3 -m py_compile \
  "${REPO}/services/project-context/main.py" \
  "$CLI"

if busctl --user --list 2>/dev/null | grep -q 'org.adaptive.ProjectContext'; then
  "$CLI" status
else
  echo "Project Context DBus service is not running in this user session."
  echo "Log out and back into Adaptive Desktop, or run:"
  echo "  ${REPO}/services/project-context/main.py"
fi
