#!/usr/bin/env bash
set -Eeuo pipefail

cd "${HOME}/adaptive-desktop"
exec python3 apps/adaptive-projects/main.py "$@"
