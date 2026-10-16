#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
SERVICE_DIR="${REPO}/services/project-context"
AUTOSTART_DIR="${HOME}/.config/autostart"
APPLICATIONS_DIR="${HOME}/.local/share/applications"
SEARCH_PROVIDER_DIR="${HOME}/.local/share/gnome-shell/search-providers"

mkdir -p \
  "$AUTOSTART_DIR" \
  "$APPLICATIONS_DIR" \
  "$SEARCH_PROVIDER_DIR"

# The entry in the repo names the original machine's checkout; point it at
# this one, so the service starts for any user name.
for target in "${AUTOSTART_DIR}" "${APPLICATIONS_DIR}"; do
  sed "s|/home/karthi/adaptive-desktop|${REPO}|g" \
    "${SERVICE_DIR}/adaptive-project-context.desktop" \
    > "${target}/adaptive-project-context.desktop"
  chmod 644 "${target}/adaptive-project-context.desktop"
done

install -m 644 \
  "${SERVICE_DIR}/org.adaptive.ProjectContext.search-provider.ini" \
  "${SEARCH_PROVIDER_DIR}/org.adaptive.ProjectContext.search-provider.ini"

echo "Adaptive Project Context installed:"
echo "  autostart: ${AUTOSTART_DIR}/adaptive-project-context.desktop"
echo "  desktop:   ${APPLICATIONS_DIR}/adaptive-project-context.desktop"
echo "  search:    ${SEARCH_PROVIDER_DIR}/org.adaptive.ProjectContext.search-provider.ini"
