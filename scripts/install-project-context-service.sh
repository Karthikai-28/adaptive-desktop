#!/usr/bin/env bash
set -Eeuo pipefail

. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/adaptive-paths.sh"
REPO="$ADAPTIVE_REPO"
SERVICE_DIR="${REPO}/services/project-context"
AUTOSTART_DIR="${HOME}/.config/autostart"
APPLICATIONS_DIR="${HOME}/.local/share/applications"
SEARCH_PROVIDER_DIR="${HOME}/.local/share/gnome-shell/search-providers"

mkdir -p \
  "$AUTOSTART_DIR" \
  "$APPLICATIONS_DIR" \
  "$SEARCH_PROVIDER_DIR"

for target in "${AUTOSTART_DIR}" "${APPLICATIONS_DIR}"; do
  adaptive_render "${SERVICE_DIR}/adaptive-project-context.desktop" "${target}/adaptive-project-context.desktop"
done

install -m 644 \
  "${SERVICE_DIR}/org.adaptive.ProjectContext.search-provider.ini" \
  "${SEARCH_PROVIDER_DIR}/org.adaptive.ProjectContext.search-provider.ini"

echo "Adaptive Project Context installed:"
echo "  autostart: ${AUTOSTART_DIR}/adaptive-project-context.desktop"
echo "  desktop:   ${APPLICATIONS_DIR}/adaptive-project-context.desktop"
echo "  search:    ${SEARCH_PROVIDER_DIR}/org.adaptive.ProjectContext.search-provider.ini"
