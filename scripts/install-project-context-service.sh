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

install -m 644 \
  "${SERVICE_DIR}/adaptive-project-context.desktop" \
  "${AUTOSTART_DIR}/adaptive-project-context.desktop"

install -m 644 \
  "${SERVICE_DIR}/adaptive-project-context.desktop" \
  "${APPLICATIONS_DIR}/adaptive-project-context.desktop"

install -m 644 \
  "${SERVICE_DIR}/org.adaptive.ProjectContext.search-provider.ini" \
  "${SEARCH_PROVIDER_DIR}/org.adaptive.ProjectContext.search-provider.ini"

echo "Adaptive Project Context installed:"
echo "  autostart: ${AUTOSTART_DIR}/adaptive-project-context.desktop"
echo "  desktop:   ${APPLICATIONS_DIR}/adaptive-project-context.desktop"
echo "  search:    ${SEARCH_PROVIDER_DIR}/org.adaptive.ProjectContext.search-provider.ini"
